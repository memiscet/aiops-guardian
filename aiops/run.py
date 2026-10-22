import argparse
import asyncio
import json
import uuid
from pathlib import Path
from dotenv import load_dotenv
from langgraph.types import Command
from .audit import DEFAULT_DIR, AuditLog, now
from .limits import BudgetedLLM, Limits
from .mcp_adapter import collect
from .pricing import load_pricing
from .sinks import sink_from_env
from .workflow import LLM, build_graph


async def main():
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument("--namespace", default="stage4-lab")
    parser.add_argument("--pod", required=True)
    parser.add_argument("--fixture", help="Read sample evidence instead of connecting to MCP")
    parser.add_argument("--audit-dir", default=str(DEFAULT_DIR))
    parser.add_argument("--no-publish", action="store_true", help="do not write the report/event to local MiniStack (S3/SQS)")
    args = parser.parse_args()
    pricing, limits = load_pricing(), Limits.load()
    audit = AuditLog(Path(args.audit_dir))
    flags = {}
    started = now()
    if args.fixture:
        evidence = open(args.fixture).read()
    else:
        ev = await collect(args.namespace, args.pod)
        evidence = ev.text
        flags = {"logs_collected": ev.logs_collected, "injection_suspected": ev.injection_suspected}
        audit.event("collect_evidence", "step", "passed", started=started, agent_id="mcp-adapter",
                    outputs=[audit.artifact(evidence, "text/plain"), audit.artifact({"tool_calls": ev.tool_calls, "redactions": ev.redactions})])
    llm = BudgetedLLM(LLM(max_output_tokens=limits.max_output_tokens_per_call), limits, pricing)
    graph = build_graph(llm, audit, pricing, sink=None if args.no_publish else sink_from_env())
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    output = graph.invoke({"namespace": args.namespace, "pod": args.pod, "evidence": evidence, "usage": [], **flags}, config=config)
    if "__interrupt__" in output:
        print("APPROVAL REQUEST:\n", output["__interrupt__"])
        decision = input("Approve dry-run recommendation? [yes/NO]: ").strip().lower() == "yes"
        output = graph.invoke(Command(resume=decision), config=config)
    print(json.dumps({k: v for k, v in output.items() if k != "evidence"}, indent=2))
    print(f"audit trail: {audit.path} (run {audit.run_id})")


if __name__ == "__main__":
    asyncio.run(main())
