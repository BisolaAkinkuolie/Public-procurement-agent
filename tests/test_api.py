import json
from contextlib import asynccontextmanager

from fastapi.testclient import TestClient

from procurement_agent.agent.orchestrator import ProcurementAgent
from procurement_agent.agent.toolbox import Toolbox
from procurement_agent.api.app import create_app
from procurement_agent.llm import ChatResponse, ScriptedChatModel, ToolCall


def make_client(mcp_server, responses):
    @asynccontextmanager
    async def factory():
        async with Toolbox(mcp_server, None) as tb:
            yield ProcurementAgent(ScriptedChatModel(list(responses)), tb)

    return TestClient(create_app(session_factory=factory))


def test_health(mcp_server):
    assert make_client(mcp_server, []).get("/health").json()["status"] == "ok"


def test_chat_returns_answer_trace_and_grounding(mcp_server):
    client = make_client(
        mcp_server,
        [
            ChatResponse(None, [ToolCall("c1", "describe_data", "{}")]),
            ChatResponse("The dataset covers 10 vendors."),
        ],
    )
    body = client.post("/chat", json={"question": "What does the data cover?"}).json()
    assert body["answer"].startswith("The dataset covers")
    assert body["tool_trace"][0]["tool"] == "describe_data"
    assert body["grounding"]["ok"] is True
    json.dumps(body)  # fully serialisable


def test_blank_question_is_rejected(mcp_server):
    r = make_client(mcp_server, []).post("/chat", json={"question": "   "})
    assert r.status_code == 400


def test_chat_page_is_served(mcp_server):
    r = make_client(mcp_server, []).get("/")
    assert r.status_code == 200 and "Public Procurement Agent" in r.text
