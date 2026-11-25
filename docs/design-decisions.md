# Design decisions

Short records of the choices that shape this project, and why. Each one is a question an interviewer is
likely to ask.

## 1. The model never writes SQL

**Decision:** The agent reaches the database only through six MCP tools with typed, validated arguments.
Every query is built with SQLAlchemy Core and uses bound parameters.

**Why:** Text-to-SQL is impressive in a demo and risky in production. It can read tables it shouldn't,
run expensive scans and fall for prompt injection. Typed tools cover the questions people actually ask
(rankings, profiles, breakdowns, competition, search). They also give a smaller, auditable surface: argument
limits (`limit ≤ 25`, `year 2000–2100`, enum fields) are enforced by schema before any code runs.

**Trade-off:** Questions outside the tools' shape can't be answered. The agent says so instead of improvising.

## 2. Approved views, enforced twice

**Decision:** The tools may only reference `v_contracts`, `v_vendor_summary` and `v_spend_by_year`. A test
captures every SQL statement the tools execute and fails if any other table appears. In Azure SQL, the
agent's managed identity is granted SELECT on those views and explicitly denied on the base table
(`infra/sql/agent_reader.sql`).

**Why:** Code-level and database-level controls fail independently. Views also let us leave out fields that
can relate to identifiable individuals (`vendor_postal_code`, `former_public_servant`).

## 3. Counting money correctly: `committed_value`

**Decision:** At ingest, each row gets a `committed_value`. A new contract contributes its original value,
an amendment row (`instrument_type = 'A'`) contributes only its amendment value, and standing offer
agreement rows (`SOSA`) are excluded from spend.

**Why:** The published data reports amendments as separate rows that carry the new *total* value. Summing
`contract_value` across rows double counts every amended contract. A standing offer is an agreement, not
spend; the call-ups against it are the spend.

## 4. Vendor name normalisation

**Decision:** `vendor_key` strips case, punctuation and legal suffixes (Inc, Ltd, Corp, Ltée…) so
"ACME CONSULTING INC." and "Acme Consulting Inc" rank as one vendor.

**Trade-off:** Distinct companies that differ only by suffix will merge. Rankings show the display name and
transaction count so a reviewer can spot this.

## 5. Parent/child chunking with a relevance floor

**Decision:** Policy pages are split along their own heading hierarchy. Small child chunks (~600 chars) are
embedded and matched; the full parent section is what the model reads. Matches below a cosine similarity
floor are dropped.

**Why:** Small chunks match sharply, but requirements read out of context are easy to misstate. The floor
means an off-topic question gets "the indexed policies don't cover this" instead of a confidently cited,
irrelevant passage. Citations carry the heading path ("Directive… — 4. Requirements > 4.1 …").

## 6. Numeric grounding check after generation

**Decision:** Every figure in the final answer is matched against the numbers the tools actually returned
(with tolerance for rounding like "$16.5 million"). Unmatched figures are listed under the answer and
reported in the API response.

**Why:** For an analytics assistant, the failure that matters most is a plausible invented number. This check
is deterministic, free, and also serves as an eval metric.

## 7. One codebase, two modes

**Decision:** `PA_MODE=local` runs on any OpenAI-compatible endpoint (OpenAI or Ollama), SQLite and a numpy
index. `PA_MODE=azure` uses Azure OpenAI, Azure AI Search and Azure SQL with Entra ID auth and no keys.

**Why:** Reviewers can clone and run it in minutes, and the Azure path shows how it would be deployed in an
enterprise: private endpoints, managed identity, least-privilege roles, App Insights.

## 8. MCP as the integration boundary

**Decision:** The data tools live in an MCP server that runs in-process for simplicity or as a separate
streamable-HTTP service (`PA_MCP_URL`).

**Why:** The same governed tools can be reused by other agents and clients (Azure AI Foundry, Copilot Studio,
Claude, VS Code) without re-implementing the access controls.
