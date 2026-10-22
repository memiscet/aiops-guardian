"""Stage 4 prototype: evidence -> diagnosis -> citation guardrail -> plan -> action policy -> human approval -> report.
No remediation commands are executed. Every step is written to an append-only audit trail.
"""
import json
import os
import re
import time
from typing import Literal, TypedDict
from pydantic import BaseModel
from openai import OpenAI
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import interrupt
from .audit import NullAudit, model_usage, now
from .guardrails import ACTION_RULE, CITATION_RULE, LOG_RULE, normalize_plan, verify_citations
from .policy import decide
from .pricing import Pricing, load_pricing
from .prompts import prompt

Category = Literal["app_exit_nonzero", "oom_killed", "image_pull_failure", "insufficient_evidence", "other"]
Source = Literal["pod_status", "container_state", "events", "resources", "logs"]


class Citation(BaseModel):
    source: Source
    quote: str


class Diagnosis(BaseModel):
    category: Category
    root_cause: str
    evidence: list[Citation]
    confidence: float
    uncertainty: str


class Plan(BaseModel):
    action: Literal["observe", "collect_logs", "create_report", "restart_deployment", "rollback_deployment", "change_memory_limit", "delete_namespace", "delete_cluster", "delete_pvc", "exec_shell"]
    reason: str


class State(TypedDict, total=False):
    namespace: str
    pod: str
    evidence: str
    logs_collected: bool
    injection_suspected: bool
    diagnosis: dict
    diagnosis_ok: bool
    plan: dict
    policy: str
    approved: bool
    decision: str
    result: str
    usage: list[dict]


class LLM:
    def __init__(self, model: str | None = None, max_output_tokens: int = 800, timeout: float = 60.0):
        self.client = OpenAI(max_retries=0, timeout=timeout)
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
        self.max_output_tokens = max_output_tokens

    def parse(self, schema, instructions, content):
        response = self.client.responses.parse(
            model=self.model,
            instructions=instructions,
            input=content,
            text_format=schema,
            max_output_tokens=self.max_output_tokens,
        )
        if response.output_parsed is None:
            raise RuntimeError("LLM returned no parsed output")
        u = response.usage
        return response.output_parsed.model_dump(), {
            "provider": "openai",
            "response_id": response.id,
            "model": response.model,
            "input_tokens": getattr(u, "input_tokens", None),
            "output_tokens": getattr(u, "output_tokens", None),
            "cached_input_tokens": getattr(getattr(u, "input_tokens_details", None), "cached_tokens", None),
            "reasoning_tokens": getattr(getattr(u, "output_tokens_details", None), "reasoning_tokens", None),
        }


def _derive_logs_collected(evidence: str) -> bool:
    return bool(re.search(r"<<<UNTRUSTED_LOG|Previous logs:", evidence)) and "no logs available" not in evidence


def build_graph(llm=None, audit=None, pricing: Pricing | None = None, max_attempts: int = 1):
    llm = llm or LLM()
    audit = audit or NullAudit()
    pricing = pricing or load_pricing()

    def model_step(step: str, step_id: str, agent: str, schema, content: str):
        text, version, sha = prompt(step)
        inputs = [audit.artifact({"prompt_version": version, "prompt_sha256": sha, "input": content})]
        for attempt in range(max_attempts):
            t0, started = time.perf_counter(), now()
            try:
                parsed, usage = llm.parse(schema, text, content)
            except Exception as exc:
                category = "budget" if type(exc).__name__ == "BudgetExceeded" else "model_api"
                audit.event(step_id, "model_call", "error", started=started, agent_id=agent, agent_version=version, inputs=inputs,
                            retry=attempt, failure_origin=step_id,
                            error={"category": category, "code": type(exc).__name__, "message_redacted": str(exc)})
                if category == "budget" or attempt == max_attempts - 1:
                    raise
                continue
            latency = int((time.perf_counter() - t0) * 1000)
            record = model_usage(usage, version, sha, latency, pricing)
            audit.event(step_id, "model_call", "passed", started=started, agent_id=agent, agent_version=version, inputs=inputs,
                        outputs=[audit.artifact(parsed)], usage=record, retry=attempt)
            return parsed, {"prompt_version": version, "latency_ms": latency, "cost": record["cost"],
                            "cost_status": record["cost_status"], **usage}

    def analyze(s: State):
        parsed, usage = model_step("diagnosis", "analyze", "diagnosis-agent", Diagnosis, s["evidence"])
        return {"diagnosis": parsed, "usage": s.get("usage", []) + [{"step": "diagnosis", **usage}],
                "logs_collected": s["logs_collected"] if "logs_collected" in s else _derive_logs_collected(s["evidence"])}

    def verify(s: State):
        ok, reason = verify_citations(s["diagnosis"], s["evidence"])
        audit.event("analyze", "guardrail", "passed" if ok else "failed", failure_origin=None if ok else "analyze",
                    inputs=[audit.artifact(s["diagnosis"])],
                    guardrail={"rule_id": CITATION_RULE[0], "rule_version": CITATION_RULE[1], "result": "pass" if ok else "fail", "reason": reason})
        return {"diagnosis_ok": ok}

    def after_verify(s: State):
        return "plan" if s["diagnosis_ok"] else "report"

    def plan(s: State):
        content = json.dumps({"diagnosis": s["diagnosis"], "namespace": s["namespace"], "logs_already_collected": s["logs_collected"]})
        parsed, usage = model_step("planning", "plan", "planning-agent", Plan, content)
        parsed, note = normalize_plan(parsed, s["logs_collected"])
        if note:
            audit.event("plan", "guardrail", "passed", inputs=[audit.artifact(parsed)],
                        guardrail={"rule_id": LOG_RULE[0], "rule_version": LOG_RULE[1], "result": "fail", "reason": note})
        return {"plan": parsed, "usage": s["usage"] + [{"step": "planning", **usage}]}

    def policy(s: State):
        decision = decide(s["plan"]["action"], s["namespace"])
        blocked = decision == "blocked"
        audit.event("policy", "guardrail", "failed" if blocked else "passed", failure_origin="plan" if blocked else None,
                    inputs=[audit.artifact(s["plan"])],
                    guardrail={"rule_id": ACTION_RULE[0], "rule_version": ACTION_RULE[1], "result": "fail" if blocked else "pass",
                               "reason": f"action {s['plan']['action']!r} in namespace {s['namespace']!r}: {decision}"})
        return {"policy": decision}

    def route(s: State):
        return "approval_request" if s["policy"] == "approval_required" else "report"

    def approval_request(s: State):
        ref = audit.artifact(s["plan"])
        audit.event("approval", "punch_out", "awaiting_human_approval", inputs=[ref],
                    punch_out={"decision_point_id": "approve-remediation", "decision": "awaiting", "approver_role": None,
                               "approval_reference": None, "bound_artifact_sha256": ref["sha256"]})
        return {}

    def approval(s: State):
        # Re-runs on resume; no side effects before interrupt.
        response = interrupt({"question": "Approve suggested action? (no execution in prototype)", "plan": s["plan"]})
        approved = response is True
        ref = audit.artifact(s["plan"])
        audit.event("approval", "punch_out", "approved_to_resume" if approved else "rejected_by_human", inputs=[ref],
                    punch_out={"decision_point_id": "approve-remediation", "decision": "approved" if approved else "rejected",
                               "approver_role": "console-operator (unauthenticated demo)", "approval_reference": None,
                               "bound_artifact_sha256": ref["sha256"]})
        return {"approved": approved}

    def report(s: State):
        if not s["diagnosis_ok"]:
            decision, result, origin = "rejected_by_guardrail", "rejected: diagnosis failed evidence verification", "analyze"
        elif s["policy"] == "blocked":
            decision, result, origin = "blocked", "blocked by policy", "plan"
        elif s["policy"] == "approval_required" and s.get("approved"):
            decision, result, origin = "approved", "approved (dry run; no changes executed)", None
        elif s["policy"] == "approval_required":
            decision, result, origin = "denied", "denied by human", "approval"
        else:
            decision, result, origin = "allowed", "allowed (dry run; no changes executed)", None
        status = "rejected_by_human" if decision == "denied" else "failed" if origin else "passed"
        audit.event("report", "workflow_terminal", status, failure_origin=origin, outputs=[audit.artifact({"decision": decision, "result": result})])
        return {"decision": decision, "result": result}

    graph = StateGraph(State)
    for name, fn in [("analyze", analyze), ("verify", verify), ("plan", plan), ("policy", policy),
                     ("approval_request", approval_request), ("approval", approval), ("report", report)]:
        graph.add_node(name, fn)
    graph.add_edge(START, "analyze")
    graph.add_edge("analyze", "verify")
    graph.add_conditional_edges("verify", after_verify)
    graph.add_edge("plan", "policy")
    graph.add_conditional_edges("policy", route)
    graph.add_edge("approval_request", "approval")
    graph.add_edge("approval", "report")
    graph.add_edge("report", END)
    return graph.compile(checkpointer=InMemorySaver())
