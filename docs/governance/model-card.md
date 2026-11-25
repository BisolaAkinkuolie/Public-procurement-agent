# System card: Public Procurement Agent

## Purpose

Help analysts explore Government of Canada contracts over $10,000 and look up related procurement policy,
with every figure traceable to the published data and every policy statement traceable to a cited section.

## Intended users and uses

- Analysts, journalists, researchers and procurement staff exploring spending patterns.
- Questions about vendors, departments, categories, trends and competition, and what policy says.

## Out of scope

- Making or recommending decisions about any vendor, contract or person.
- Legal advice or authoritative policy interpretation. The agent quotes and cites; it does not rule.
- Allegations of wrongdoing. The system prompt forbids them, and the golden eval set tests for this.

## Data

| Source | What | How it is used |
|---|---|---|
| Proactive Publication – Contracts over $10,000 (open.canada.ca, TBS) | Contract records published by federal entities | Loaded into a database; exposed through three approved views |
| TBS directives, PSPC Code of Conduct for Procurement, Government Contracts Regulations | Public policy text | Fetched at setup, chunked and embedded for retrieval |
| `data/sample/contracts_sample.csv` | **Synthetic** records | Tests, CI and offline demos only |

Fields that can relate to identifiable individuals (`vendor_postal_code`, `former_public_servant`) are
loaded but not exposed to the agent.

## Known limitations

- Published data quality varies by department: blank original values, inconsistent vendor names and late
  publication are all common. `vendor_key` normalisation reduces, but does not eliminate, split or merged
  vendors.
- Values include taxes and reflect what departments reported, not invoiced or paid amounts.
- Policy retrieval covers only the indexed documents and is only as current as the last `ingest-docs` run.
- The numeric grounding check confirms a figure *appears* in a tool result, not that it was used in the right
  context.

## Controls

| Risk | Control | Verified by |
|---|---|---|
| Invented figures | Numeric grounding check on every answer | `tests/test_guardrails.py`, eval metric `grounded` |
| Unauthorised data access | Typed MCP tools; approved views only; DB login limited to SELECT on views | `tests/test_mcp_server.py::test_tools_only_touch_approved_views`, `infra/sql/agent_reader.sql` |
| SQL injection / prompt injection into queries | No model-written SQL; bound parameters; schema-validated arguments | `test_sql_injection_is_inert`, `test_invalid_arguments_are_rejected` |
| Runaway tool loops / cost | Step budget (default 6); row cap per call (25) | `test_step_budget_is_enforced` |
| Uncited or irrelevant policy claims | Relevance floor; citation strings from retrieval | `test_relevance_floor_returns_nothing_for_off_topic_queries`, eval metric `policy_cited` |
| Defamatory conclusions | Prompt rule; eval case `no-accusation` | `evals/golden_set.jsonl` |
| Secrets exposure | Entra ID auth; keys disabled on Azure resources | `infra/main.bicep` (`disableLocalAuth: true`) |

## Monitoring

In Azure mode, OpenTelemetry spans for each question and tool call go to Application Insights. Answers
with ungrounded figures are logged at WARNING level.
