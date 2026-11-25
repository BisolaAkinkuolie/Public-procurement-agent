"""The agent loop: plan with tools, answer, then verify the answer against what the tools returned."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from procurement_agent.agent.guardrails import (
    GroundingReport,
    annotate,
    check_numeric_grounding,
    check_question,
)
from procurement_agent.agent.prompts import SYSTEM_PROMPT
from procurement_agent.agent.toolbox import Toolbox
from procurement_agent.llm import ChatModel
from procurement_agent.telemetry import span

log = logging.getLogger(__name__)


@dataclass
class ToolTraceEntry:
    tool: str
    arguments: dict[str, Any]
    ms: int
    output_preview: str


@dataclass
class AgentResult:
    answer: str
    tool_trace: list[ToolTraceEntry] = field(default_factory=list)
    policy_citations: list[str] = field(default_factory=list)
    grounding: GroundingReport = field(default_factory=GroundingReport)
    steps: int = 0
    completed: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "answer": self.answer,
            "completed": self.completed,
            "steps": self.steps,
            "tool_trace": [t.__dict__ for t in self.tool_trace],
            "policy_citations": self.policy_citations,
            "grounding": {
                "ok": self.grounding.ok,
                "checked": self.grounding.checked,
                "ungrounded": self.grounding.ungrounded,
            },
        }


class ProcurementAgent:
    def __init__(self, llm: ChatModel, toolbox: Toolbox, max_steps: int = 6):
        self.llm = llm
        self.toolbox = toolbox
        self.max_steps = max_steps

    async def ask(self, question: str) -> AgentResult:
        question = check_question(question)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": question},
        ]
        result = AgentResult(answer="")
        tool_outputs: list[str] = []

        with span("agent.ask", question_chars=len(question)):
            for step in range(1, self.max_steps + 1):
                result.steps = step
                resp = await asyncio.to_thread(self.llm.chat, messages, self.toolbox.tools)

                if not resp.tool_calls:
                    report = check_numeric_grounding(resp.content or "", tool_outputs)
                    result.grounding = report
                    result.answer = annotate(resp.content or "", report)
                    if not report.ok:
                        log.warning("ungrounded figures in answer: %s", report.ungrounded)
                    return result

                messages.append(
                    {
                        "role": "assistant",
                        "content": resp.content,
                        "tool_calls": [
                            {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.arguments}}
                            for c in resp.tool_calls
                        ],
                    }
                )
                for call in resp.tool_calls:
                    started = time.perf_counter()
                    with span("agent.tool", tool=call.name):
                        output = await self.toolbox.call(call.name, call.arguments)
                    elapsed = int((time.perf_counter() - started) * 1000)
                    tool_outputs.append(output)
                    try:
                        args = json.loads(call.arguments or "{}")
                    except json.JSONDecodeError:
                        args = {"_raw": call.arguments}
                    result.tool_trace.append(ToolTraceEntry(call.name, args, elapsed, output[:300]))
                    if call.name == "search_policy":
                        try:
                            for p in json.loads(output).get("passages", []):
                                result.policy_citations.append(p["citation"])
                        except (json.JSONDecodeError, AttributeError, KeyError):
                            pass
                    messages.append({"role": "tool", "tool_call_id": call.id, "content": output})

        result.completed = False
        result.answer = (
            "I couldn't finish this within the tool-call budget. Try a narrower question, for example one "
            "department, one vendor or a specific year range."
        )
        return result
