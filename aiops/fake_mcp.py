"""Offline stand-in for the Kubernetes MCP server, driven by gold-case data. Advertises the pinned tool list."""
import json
from types import SimpleNamespace as NS

from .mcp_adapter import PINNED_TOOLS_FILE, Settings

OFFLINE_SETTINGS = Settings(command="offline", args=(), kubeconfig="offline")


def _ok(value):
    structured = {"result": value} if isinstance(value, (list, str)) else value
    return NS(isError=False, content=[NS(text=value if isinstance(value, str) else json.dumps(value))], structuredContent=structured)


def _err(text):
    return NS(isError=True, content=[NS(text=text)], structuredContent=None)


class FakeSession:
    def __init__(self, mcp: dict, settings: Settings = OFFLINE_SETTINGS):
        self.mcp, self.s = mcp, settings
        self.calls: list[tuple[str, dict]] = []

    async def list_tools(self):
        return NS(tools=[NS(name=t["name"], inputSchema=t["inputSchema"]) for t in json.loads(PINNED_TOOLS_FILE.read_text())["tools"]])

    async def call_tool(self, name, args):
        self.calls.append((name, args))
        if name == "current_context":
            s = self.s
            return _ok({"context": s.context, "cluster": s.cluster, "user": s.user, "default_namespace": s.namespace,
                        "api_server": s.api_server, "allowed_namespaces": [s.namespace]})
        if name == "describe_pod":
            return _ok(self.mcp["describe_pod"])
        if name == "get_recent_events":
            return _ok(self.mcp["events"])
        if name == "get_pod_logs":
            text = self.mcp["logs"]["previous" if args.get("previous") else "current"]
            return _ok(text) if text is not None else _err("Kubernetes API error 400: container log not available")
        raise AssertionError(f"unexpected tool {name}")
