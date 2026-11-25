"""Deterministic guardrails around the model.

The most useful one here is the *numeric grounding check*: every figure in the final answer must be
traceable to a number some tool actually returned. It runs after generation, costs nothing, and
catches the failure that matters most for an analytics assistant: a confident, invented number.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

MAX_QUESTION_CHARS = 2000

_SCALE = {"thousand": 1e3, "k": 1e3, "million": 1e6, "m": 1e6, "mm": 1e6, "billion": 1e9, "b": 1e9, "bn": 1e9}
_NUM = re.compile(
    r"(?<![\w.])\$?\s?(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s?(%|(?:thousand|million|billion|bn|mm|[kmb])\b)?",
    re.IGNORECASE,
)


class GuardrailError(ValueError):
    pass


def check_question(question: str) -> str:
    q = (question or "").strip()
    if not q:
        raise GuardrailError("Ask a question about Government of Canada contracts or procurement policy.")
    if len(q) > MAX_QUESTION_CHARS:
        raise GuardrailError(f"Questions are limited to {MAX_QUESTION_CHARS} characters.")
    return q


@dataclass
class GroundingReport:
    checked: list[str] = field(default_factory=list)
    ungrounded: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.ungrounded


def _numbers_in(obj) -> list[float]:
    """Every numeric value in a (possibly nested) tool result, including numbers inside strings."""
    out: list[float] = []
    if isinstance(obj, bool):
        return out
    if isinstance(obj, int | float):
        out.append(float(obj))
    elif isinstance(obj, str):
        for m in _NUM.finditer(obj):
            out.append(float(m.group(1).replace(",", "")))
    elif isinstance(obj, dict):
        for v in obj.values():
            out.extend(_numbers_in(v))
    elif isinstance(obj, list):
        for v in obj:
            out.extend(_numbers_in(v))
    return out


def _close(a: float, b: float, rel: float) -> bool:
    return abs(a - b) <= max(rel * max(abs(a), abs(b)), 0.01)


def check_numeric_grounding(answer: str, tool_outputs: list[str]) -> GroundingReport:
    source: list[float] = []
    for raw in tool_outputs:
        try:
            source.extend(_numbers_in(json.loads(raw)))
        except (json.JSONDecodeError, TypeError):
            source.extend(_numbers_in(raw))

    report = GroundingReport()
    for m in _NUM.finditer(answer):
        token = m.group(0).strip()
        value = float(m.group(1).replace(",", ""))
        unit = (m.group(2) or "").lower()
        if not unit and value.is_integer() and (value < 10 or 1990 <= value <= 2100):
            continue  # small counts like "top 5" and calendar years are not claims about the data
        if re.fullmatch(r"\d+(\.\d+)*", token) and re.search(rf"(section|§)\s*{re.escape(token)}", answer, re.I):
            continue  # policy section numbers
        report.checked.append(token)
        if unit == "%":
            ok = any(_close(value, s, 0.01) or _close(value, s * 100, 0.01) for s in source)
        elif unit in _SCALE:
            # "16.5 million" is a rounded figure: accept anything that rounds to it.
            scaled = value * _SCALE[unit]
            ok = any(_close(scaled, s, 0.05) for s in source)
        else:
            ok = any(_close(value, s, 0.005) for s in source)
        if not ok:
            report.ungrounded.append(token)
    return report


def annotate(answer: str, report: GroundingReport) -> str:
    if report.ok:
        return answer
    figures = ", ".join(dict.fromkeys(report.ungrounded))
    return (
        f"{answer}\n\n> Note: these figures could not be matched to any tool result and should not be relied "
        f"on: {figures}."
    )
