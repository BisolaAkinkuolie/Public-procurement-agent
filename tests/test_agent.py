import json

from procurement_agent.agent.orchestrator import ProcurementAgent
from procurement_agent.agent.toolbox import Toolbox
from procurement_agent.llm import ChatResponse, ScriptedChatModel, ToolCall


async def run(mcp_server, retriever, responses, max_steps=6):
    llm = ScriptedChatModel(responses)
    async with Toolbox(mcp_server, retriever) as tb:
        result = await ProcurementAgent(llm, tb, max_steps=max_steps).ask("Who are the top goods vendors?")
    return llm, result


async def test_tool_list_includes_mcp_tools_and_policy_search(mcp_server, retriever):
    async with Toolbox(mcp_server, retriever) as tb:
        names = {t["function"]["name"] for t in tb.tools}
    assert {"top_vendors", "search_policy"} <= names


async def test_agent_answers_from_tool_results_and_passes_grounding(mcp_server, retriever):
    # First find out what the tool will actually return, so the scripted answer quotes it.
    async with Toolbox(mcp_server, None) as tb:
        top = json.loads(await tb.call("top_vendors", json.dumps({"commodity_type": "G", "limit": 1})))["rows"][0]

    llm, result = await run(
        mcp_server,
        retriever,
        [
            ChatResponse(None, [ToolCall("c1", "top_vendors", json.dumps({"commodity_type": "G", "limit": 1}))]),
            ChatResponse(f"{top['vendor_name']} leads goods with ${top['committed_value']:,.2f}."),
        ],
    )
    assert result.completed and result.grounding.ok
    assert result.tool_trace[0].tool == "top_vendors"
    # The tool result was fed back to the model as a tool message.
    assert llm.calls[1][-1]["role"] == "tool"


async def test_invented_number_is_flagged_in_the_answer(mcp_server, retriever):
    _, result = await run(
        mcp_server,
        retriever,
        [
            ChatResponse(None, [ToolCall("c1", "top_vendors", json.dumps({"commodity_type": "G", "limit": 1}))]),
            ChatResponse("The top goods vendor received $99,999,999."),
        ],
    )
    assert not result.grounding.ok
    assert "could not be matched" in result.answer


async def test_policy_citations_are_collected(mcp_server, retriever):
    _, result = await run(
        mcp_server,
        retriever,
        [
            ChatResponse(None, [ToolCall("c1", "search_policy", json.dumps({"query": "award without competition"}))]),
            ChatResponse("Policy allows it in emergencies [Policy: Sample]."),
        ],
    )
    assert any("Exceptions to competition" in c for c in result.policy_citations)


async def test_bad_tool_arguments_are_returned_to_the_model_not_raised(mcp_server, retriever):
    llm, result = await run(
        mcp_server,
        retriever,
        [
            ChatResponse(None, [ToolCall("c1", "top_vendors", "{not json")]),
            ChatResponse(None, [ToolCall("c2", "top_vendors", json.dumps({"limit": 999}))]),
            ChatResponse(None, [ToolCall("c3", "drop_tables", "{}")]),
            ChatResponse("Sorry, I could not get that."),
        ],
    )
    tool_msgs = [m["content"] for m in llm.calls[-1] if m["role"] == "tool"]
    assert all("error" in json.loads(m) for m in tool_msgs)
    assert result.completed


async def test_step_budget_is_enforced(mcp_server, retriever):
    loop = [ChatResponse(None, [ToolCall(f"c{i}", "describe_data", "{}")]) for i in range(3)]
    _, result = await run(mcp_server, retriever, loop, max_steps=3)
    assert not result.completed
    assert result.steps == 3
