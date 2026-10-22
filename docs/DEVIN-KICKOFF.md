# Devin Desktop kickoff — AIOps Guardian / Improving Stage 4

## Paste this into Devin Desktop

You are joining my existing **AIOps Guardian** project for Improving's Stage 4 AI certification. First read `AGENTS.md` and `README.md` in this repository and inspect all source and tests. I have Stage 3 certification and am a Principal DevOps Consultant.

Our final demonstration is a reproducible, safe, evaluated multi-agent Kubernetes incident workflow, not simply an LLM chatbot. The harness is **Devin Desktop**. The model is the **hosted OpenAI API**; infrastructure is **local Vagrant Kubernetes** and **MiniStack AWS emulator**, not real AWS. I have pre-existing **Kubernetes** and **DevOpsninja** MCP servers in other local/private repos. Do not assume their paths, tool names, or contracts. Discover them with my help if needed.

**Your immediate assignment**: (1) audit the starter and run available tests; (2) list the exact MCP interfaces from my existing servers and connect the read-only diagnostics adapter to Kubernetes; (3) execute the synthetic CrashLoopBackOff fixture path; (4) prepare a guarded live-local-cluster test plan; (5) add repeatable evaluation cases and step-level telemetry with measured results. Do not execute Kubernetes remediations, touch real AWS, or commit secrets. Require my explicit approval before applying the test crash manifest. Log sanitized results and token usage. Report changes and test evidence in a concise handoff to ChatGPT after each milestone.

Please start by showing a brief inventory of the current code and the specific blocking facts needed from my machine. Then implement the first milestone, keeping changes small and tested.

## What Devin should return for review
- Repository path and git branch; changed files and diff summary.
- Python/OpenAI/LangGraph/MCP versions and test command/result.
- MCP tool schema inventory: name, purpose, required args, read/write risk.
- Evidence of Kubernetes local context (`kubectl config current-context` + cluster endpoint, with sensitive details removed).
- One fixture-based run trace and safety-policy results (sanitize all input/logs).
- Open questions: tool mappings, MiniStack supported endpoints, improving certification rubric.

## Stage 4 article interpretation
Prompt-level evaluations still apply; evaluate cross-agent handoffs, branching, guardrails (incl. adversarial reviews/hooks/sentinels), explicit authorized human decisions, end-to-end monitoring, and per-prompt output/token/cost audit. Stage 4 estimated 172 hours is context, not a runtime requirement. Confirm official submission details separately.

## Current limitations / do not overclaim
The existing starter has not been proven against your actual local MCP implementation or Vagrant cluster. It uses read-only evidence collection and in-memory LangGraph checkpointing; its console approval is demo-only. MiniStack integration, durable observability, automatic remediation and the Stage 4 submission are not implemented in the starter.
