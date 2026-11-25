"""Evaluate the agent end to end against a golden question set, using the configured real model.

    python evals/run_evals.py                 # writes evals/results/<timestamp>.md

Metrics (all deterministic, no LLM-as-judge needed):
* tool selection: did the agent call every expected tool (order ignored)?
* numeric grounding: did every figure in the answer match a tool result?
* policy citation: when policy is expected, did the answer cite a retrieved passage?
* safety: forbidden phrases absent; no figures stated for out-of-scope questions.
* latency per question.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from procurement_agent.runtime import agent_session

HERE = Path(__file__).parent


async def run_case(agent, case: dict) -> dict:
    started = time.perf_counter()
    result = await agent.ask(case["question"])
    secs = time.perf_counter() - started
    called = {t.tool for t in result.tool_trace}
    expected = set(case.get("expected_tools", []))
    answer = result.answer.lower()

    checks = {
        "tools": expected <= called if expected else True,
        "grounded": result.grounding.ok,
        "policy_cited": (bool(result.policy_citations) and "[policy:" in answer) if case.get("expect_policy") else True,
        "safe": not any(p.lower() in answer for p in case.get("must_not_contain", [])),
        "no_figures": not result.grounding.checked if case.get("expect_no_figures") else True,
    }
    return {
        "id": case["id"],
        "passed": all(checks.values()),
        "checks": checks,
        "tools_called": sorted(called),
        "seconds": round(secs, 1),
        "answer": result.answer,
    }


async def main() -> int:
    cases = [json.loads(line) for line in (HERE / "golden_set.jsonl").read_text().splitlines() if line.strip()]
    results = []
    async with agent_session() as agent:
        for case in cases:
            r = await run_case(agent, case)
            results.append(r)
            print(f"{'PASS' if r['passed'] else 'FAIL'}  {r['id']:<20} {r['seconds']:>5}s  tools={r['tools_called']}")

    n = len(results)
    rate = {k: sum(r["checks"][k] for r in results) / n for k in results[0]["checks"]}
    lines = [
        f"# Eval run {datetime.now():%Y-%m-%d %H:%M}",
        "",
        f"Overall: **{sum(r['passed'] for r in results)}/{n} passed**",
        "",
        "| Metric | Pass rate |",
        "|---|---|",
        *[f"| {k} | {v:.0%} |" for k, v in rate.items()],
        "",
        f"Median latency: {sorted(r['seconds'] for r in results)[n // 2]}s",
        "",
        "## Cases",
        "",
    ]
    for r in results:
        failed = [k for k, v in r["checks"].items() if not v]
        lines += [
            f"### {r['id']}: {'PASS' if r['passed'] else 'FAIL ' + ', '.join(failed)}",
            f"Tools: {', '.join(r['tools_called']) or 'none'}",
            "",
            r["answer"],
            "",
        ]
    out = HERE / "results" / f"{datetime.now():%Y%m%d-%H%M}.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text("\n".join(lines))
    print(f"\nReport: {out}")
    return 0 if all(r["passed"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
