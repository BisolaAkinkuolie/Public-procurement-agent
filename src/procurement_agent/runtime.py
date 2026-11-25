"""Wires the agent together from settings. The only place that knows about every component."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from procurement_agent.agent.orchestrator import ProcurementAgent
from procurement_agent.agent.toolbox import Toolbox
from procurement_agent.config import Settings, get_settings
from procurement_agent.llm import ChatModel, Embedder, OpenAIChatModel, OpenAIEmbedder
from procurement_agent.rag.retriever import PolicyRetriever, default_store


def mcp_target(settings: Settings) -> Any:
    if settings.mcp_url:
        return settings.mcp_url
    from procurement_agent.db.connection import get_readonly_engine
    from procurement_agent.mcp_server.server import build_server

    return build_server(get_readonly_engine(settings.database_url), settings.max_rows_per_tool_call)


def make_retriever(settings: Settings, embedder: Embedder | None = None) -> PolicyRetriever | None:
    store = default_store(settings)
    if settings.mode == "local" and not getattr(store, "children", None):
        return None  # no policy index built yet: the agent still works, without search_policy
    return PolicyRetriever(
        embedder or OpenAIEmbedder(settings), store, settings.retrieval_top_k, settings.relevance_floor
    )


@asynccontextmanager
async def agent_session(
    settings: Settings | None = None,
    llm: ChatModel | None = None,
    retriever: PolicyRetriever | None | bool = True,
):
    settings = settings or get_settings()
    if retriever is True:
        retriever = make_retriever(settings)
    async with Toolbox(mcp_target(settings), retriever or None) as toolbox:
        yield ProcurementAgent(llm or OpenAIChatModel(settings), toolbox, settings.max_agent_steps)
