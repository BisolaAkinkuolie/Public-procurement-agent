# AI risk assessment

A lightweight assessment of the kind an AI governance intake process would ask for before a use case goes to
production. It draws on the structure of ISO/IEC 42001 (AI management systems) and the NIST AI Risk
Management Framework. It is a portfolio illustration, not a certification artefact.

## 1. Use case summary

| Item | Answer |
|---|---|
| Decision supported | Exploratory analysis of public contract data and policy look-up |
| Automated decision about a person or business? | **No.** Outputs are informational; no action is taken |
| Data sensitivity | Public open data; fields relating to individuals excluded from the agent's views |
| Users | Internal or public analysts; no end-customer decisions |
| Autonomy | Read-only tools; no write, send or purchase actions |

**Applicability of Canada's Directive on Automated Decision-Making:** the directive applies to systems used
to make or support administrative decisions about clients. This assistant makes no such decision, so it falls
outside scope. If it were ever used to screen vendors or recommend awards, that would change, and an
Algorithmic Impact Assessment would be required first.

## 2. Risk tier

Scored 1 (low) to 4 (high) on each dimension:

| Dimension | Score | Rationale |
|---|---|---|
| Impact on individuals or organisations | 2 | Wrong figures could mislead commentary about a vendor or department |
| Data sensitivity | 1 | Public data; personal-adjacent fields excluded |
| Autonomy | 1 | Read-only; a human interprets every answer |
| Transparency to the user | 1 | Tool trace, sources and grounding status are shown with every answer |
| Reversibility | 1 | No actions taken |
| Scale / exposure | 2 | Could be published publicly |

**Overall tier: Limited.** Required controls: grounding and citation, evaluation before release, monitoring,
and a clear statement of limitations (see the [system card](model-card.md)).

## 3. Control mapping (selected ISO/IEC 42001 Annex A themes)

| Theme | How this project addresses it |
|---|---|
| AI system impact assessment | This document |
| Data for AI systems: quality and provenance | Ingest documents every transformation; every tool result carries source, view and filters |
| Information for interested parties | System card; limitations shown in the README and the UI |
| Use of AI systems: intended use | Out-of-scope uses listed; prompt rules; eval cases for misuse |
| AI system lifecycle: verification and validation | Unit tests in CI; golden-set evals with pass/fail metrics |
| Monitoring and logging | OpenTelemetry to Application Insights; ungrounded-figure warnings |
| Access control and security | Entra ID only, managed identity, least-privilege roles, private endpoints, no keys |

## 4. Release checklist

- [ ] Unit tests and lint pass in CI
- [ ] Golden-set evals: tool selection ≥ 90%, grounded = 100%, policy cited ≥ 90%, safety = 100%
- [ ] `ingest-docs` run within the last 30 days
- [ ] Azure SQL agent identity limited to the three views (`infra/sql/agent_reader.sql`)
- [ ] Limitations visible to users
