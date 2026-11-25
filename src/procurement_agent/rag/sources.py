"""Public policy documents the agent can cite.

The documents are downloaded at setup time (``procurement-agent ingest-docs``) and are not
committed to this repository. Add a source by appending to POLICY_SOURCES.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PolicySource:
    slug: str
    title: str
    url: str
    publisher: str


POLICY_SOURCES: list[PolicySource] = [
    PolicySource(
        "directive-management-of-procurement",
        "Directive on the Management of Procurement",
        "https://www.tbs-sct.canada.ca/pol/doc-eng.aspx?id=32692",
        "Treasury Board of Canada Secretariat",
    ),
    PolicySource(
        "guide-proactive-publication-of-contracts",
        "Guide to the Proactive Publication of Contracts",
        "https://www.tbs-sct.canada.ca/pol/doc-eng.aspx?id=32763",
        "Treasury Board of Canada Secretariat",
    ),
    PolicySource(
        "directive-automated-decision-making",
        "Directive on Automated Decision-Making",
        "https://www.tbs-sct.canada.ca/pol/doc-eng.aspx?id=32592",
        "Treasury Board of Canada Secretariat",
    ),
    PolicySource(
        "code-of-conduct-for-procurement",
        "Code of Conduct for Procurement",
        "https://www.canada.ca/en/public-services-procurement/services/acquisitions/supplier-conduct/code.html",
        "Public Services and Procurement Canada",
    ),
    PolicySource(
        "government-contracts-regulations",
        "Government Contracts Regulations (SOR/87-402)",
        "https://laws-lois.justice.gc.ca/eng/regulations/SOR-87-402/FullText.html",
        "Justice Laws Website",
    ),
]
