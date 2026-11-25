import json

import pytest

from procurement_agent.agent.guardrails import GuardrailError, check_numeric_grounding, check_question

TOOL_OUT = json.dumps(
    {
        "rows": [
            {
                "vendor_name": "Aurora",
                "committed_value": 16468595.07,
                "transaction_count": 38,
                "competitive_share_pct": 70.8,
            }
        ]
    }
)


@pytest.mark.parametrize(
    "answer",
    [
        "Aurora received $16,468,595.07 across 38 transactions.",
        "Aurora received about $16.5 million.",
        "Aurora received $16.47M.",
        "70.8% of value was competitive.",
        "The top 5 vendors in 2024 are listed below.",  # small counts and years are not checked
    ],
)
def test_grounded_answers_pass(answer):
    assert check_numeric_grounding(answer, [TOOL_OUT]).ok


@pytest.mark.parametrize(
    "answer,bad",
    [
        ("Aurora received $21,000,000.", "$21,000,000"),
        ("Aurora received about $30 million.", "$30 million"),
        ("Competitive share was 85%.", "85%"),
    ],
)
def test_invented_figures_are_flagged(answer, bad):
    report = check_numeric_grounding(answer, [TOOL_OUT])
    assert not report.ok
    assert bad in report.ungrounded


def test_answers_with_no_tool_calls_cannot_cite_figures():
    assert not check_numeric_grounding("Spend was $4,200,000.", []).ok


def test_question_checks():
    with pytest.raises(GuardrailError):
        check_question("   ")
    with pytest.raises(GuardrailError):
        check_question("x" * 5000)
    assert check_question("  hi there ") == "hi there"
