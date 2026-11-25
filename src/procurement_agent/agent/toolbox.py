"""Bridges MCP tools and the local policy-search tool into one OpenAI-style tool list."""

from __future__ import annotations

import json
from contextlib import AsyncExitStack
from typing import Any

from mcp.client import Client

from procurement_agent.rag.retriever import PolicyRetriever

SEARCH_POLICY_TOOL = {
    "type": "function",
    "function": {
        "name": "search_policy",
        "description": (
            "Search public Government of Canada procurement policy (Treasury Board directives, Code of Conduct "
            "for Procurement, Government Contracts Regulations). Returns passages with citation strings."
        ),
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "What the policy question is about."}},
            "required": ["query"],
        },
    },
}


class Toolbox:
    """Async context manager holding an MCP client session plus the policy retriever.

    ``mcp_server`` may be an in-process MCPServer (tests, single-container deploys) or the URL of a
    remote streamable-HTTP MCP server (the same server deployed separately).
    """

    def __init__(self, mcp_server: Any, retriever: PolicyRetriever | None):
        self.mcp_server = mcp_server
        self.retriever = retriever
        self._stack = AsyncExitStack()
        self.client: Client | None = None
        self.tools: list[dict[str, Any]] = []
        self.mcp_tool_names: set[str] = set()

    async def __aenter__(self) -> Toolbox:
        self.client = await self._stack.enter_async_context(Client(self.mcp_server))
        listing = await self.client.list_tools()
        for t in listing.tools:
            self.mcp_tool_names.add(t.name)
            self.tools.append(
                {
                    "type": "function",
                    "function": {"name": t.name, "description": t.description or "", "parameters": t.input_schema},
                }
            )
        if self.retriever is not None:
            self.tools.append(SEARCH_POLICY_TOOL)
        return self

    async def __aexit__(self, *exc) -> None:
        await self._stack.aclose()

    async def call(self, name: str, arguments_json: str) -> str:
        """Run a tool and always return a string for the model, including on error."""
        try:
            args = json.loads(arguments_json or "{}")
            if not isinstance(args, dict):
                raise ValueError("tool arguments must be a JSON object")
        except (json.JSONDecodeError, ValueError) as exc:
            return json.dumps({"error": f"Invalid arguments: {exc}"})

        if name == "search_policy" and self.retriever is not None:
            passages = self.retriever.retrieve(str(args.get("query", "")))
            if not passages:
                return json.dumps({"passages": [], "note": "No indexed policy passage met the relevance floor."})
            return json.dumps({"passages": [p.to_dict() for p in passages]})

        if name not in self.mcp_tool_names:
            return json.dumps({"error": f"Unknown tool: {name}"})

        result = await self.client.call_tool(name, args)
        text = "\n".join(getattr(c, "text", "") for c in result.content)
        if result.is_error:
            return json.dumps({"error": text})
        return text
