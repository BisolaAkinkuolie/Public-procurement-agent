"""Parameterised, read-only queries over the approved views.

Design rules, enforced here rather than trusted to the model:
* No raw SQL ever comes from the model. Every query is built with SQLAlchemy Core from typed,
  validated arguments, so values are always bound parameters.
* Only the approved views are referenced. The base ``contracts`` table is never named.
* Every result is capped at ``max_rows`` and carries provenance (source, view, filters applied).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import Engine, Select, case, column, desc, func, literal, select, table

SOURCE = (
    "Government of Canada, Proactive Publication - Contracts over $10,000 "
    "(open.canada.ca, Treasury Board of Canada Secretariat)"
)

# Code lists from the dataset's data dictionary.
COMMODITY_TYPES = {"G": "Goods", "S": "Services", "C": "Construction"}
SOLICITATION_PROCEDURES = {
    "OB": "Competitive - open bidding (GETS)",
    "TC": "Competitive - traditional",
    "ST": "Competitive - selective tendering",
    "AC": "Advance Contract Award Notice (ACAN)",
    "TN": "Non-competitive",
}
COMPETITIVE = ("OB", "TC", "ST")

v_contracts = table(
    "v_contracts",
    *[
        column(c)
        for c in (
            "reference_number",
            "vendor_name",
            "vendor_key",
            "department",
            "contract_date",
            "contract_year",
            "description_en",
            "commodity_type",
            "economic_object_code",
            "solicitation_procedure",
            "instrument_type",
            "number_of_bids",
            "committed_value",
            "contract_value",
        )
    ],
)
v_vendor_summary = table(
    "v_vendor_summary",
    *[
        column(c)
        for c in (
            "vendor_key",
            "vendor_name",
            "transaction_count",
            "committed_value",
            "first_contract_date",
            "last_contract_date",
            "department_count",
        )
    ],
)
v_spend_by_year = table(
    "v_spend_by_year",
    *[
        column(c)
        for c in (
            "contract_year",
            "department",
            "commodity_type",
            "solicitation_procedure",
            "transaction_count",
            "committed_value",
        )
    ],
)

APPROVED_VIEWS = ("v_contracts", "v_vendor_summary", "v_spend_by_year")


def _like(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


@dataclass
class Filters:
    department: str | None = None
    commodity_type: str | None = None
    year_from: int | None = None
    year_to: int | None = None
    keyword: str | None = None

    def apply(self, stmt: Select, t) -> Select:
        if self.department:
            stmt = stmt.where(t.c.department.ilike(_like(self.department), escape="\\"))
        if self.commodity_type:
            stmt = stmt.where(t.c.commodity_type == self.commodity_type)
        if self.year_from is not None:
            stmt = stmt.where(t.c.contract_year >= self.year_from)
        if self.year_to is not None:
            stmt = stmt.where(t.c.contract_year <= self.year_to)
        if self.keyword and "description_en" in t.c:
            stmt = stmt.where(t.c.description_en.ilike(_like(self.keyword), escape="\\"))
        return stmt

    def as_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v is not None}


def _money(x: Any) -> float | None:
    return None if x is None else round(float(x), 2)


def _envelope(view: str, filters: dict[str, Any], rows: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    return {"source": SOURCE, "view": view, "filters": filters, "row_count": len(rows), "rows": rows, **extra}


class ProcurementQueries:
    def __init__(self, engine: Engine, max_rows: int = 25):
        self.engine = engine
        self.max_rows = max_rows

    def _fetch(self, stmt: Select) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            return [dict(r._mapping) for r in conn.execute(stmt)]

    def _cap(self, limit: int) -> int:
        return max(1, min(limit, self.max_rows))

    # -- tools ---------------------------------------------------------------------------------

    def describe_data(self) -> dict[str, Any]:
        t = v_contracts
        stmt = select(
            func.count().label("transactions"),
            func.min(t.c.contract_date).label("earliest_contract_date"),
            func.max(t.c.contract_date).label("latest_contract_date"),
            func.count(func.distinct(t.c.department)).label("departments"),
            func.count(func.distinct(t.c.vendor_key)).label("vendors"),
            func.sum(t.c.committed_value).label("committed_value"),
        ).select_from(t)
        row = self._fetch(stmt)[0]
        row["committed_value"] = _money(row["committed_value"])
        return {
            "source": SOURCE,
            "approved_views": list(APPROVED_VIEWS),
            "coverage": row,
            "commodity_types": COMMODITY_TYPES,
            "solicitation_procedures": SOLICITATION_PROCEDURES,
            "value_definition": (
                "committed_value = original contract value for new contracts, amendment value for "
                "amendment rows; standing offer agreements excluded. Values include taxes."
            ),
        }

    def top_vendors(self, filters: Filters, rank_by: str = "committed_value", limit: int = 10) -> dict[str, Any]:
        t = v_contracts
        total = func.sum(t.c.committed_value).label("committed_value")
        count = func.count().label("transaction_count")
        stmt = select(
            func.max(t.c.vendor_name).label("vendor_name"),
            count,
            total,
            func.count(func.distinct(t.c.department)).label("department_count"),
        ).where(t.c.vendor_key.is_not(None))
        stmt = filters.apply(stmt, t).group_by(t.c.vendor_key)
        stmt = stmt.order_by(desc(total if rank_by == "committed_value" else count)).limit(self._cap(limit))
        rows = self._fetch(stmt)
        for i, r in enumerate(rows, start=1):
            r["rank"] = i
            r["committed_value"] = _money(r["committed_value"])
        return _envelope("v_contracts", {**filters.as_dict(), "rank_by": rank_by}, rows)

    def vendor_profile(self, vendor: str, recent: int = 5) -> dict[str, Any]:
        from procurement_agent.db.ingest import normalise_vendor

        key = normalise_vendor(vendor) or vendor.upper()
        s = v_vendor_summary
        matches = self._fetch(
            select(s).where(s.c.vendor_key.ilike(_like(key), escape="\\")).order_by(desc(s.c.committed_value)).limit(5)
        )
        if not matches:
            return _envelope("v_vendor_summary", {"vendor": vendor}, [], note="No vendor matched that name.")
        best = matches[0]
        best["committed_value"] = _money(best["committed_value"])
        t = v_contracts
        by_dept = self._fetch(
            select(t.c.department, func.sum(t.c.committed_value).label("committed_value"), func.count().label("n"))
            .where(t.c.vendor_key == best["vendor_key"])
            .group_by(t.c.department)
            .order_by(desc("committed_value"))
            .limit(5)
        )
        by_proc = self._fetch(
            select(t.c.solicitation_procedure, func.count().label("n"), func.sum(t.c.committed_value).label("value"))
            .where(t.c.vendor_key == best["vendor_key"])
            .group_by(t.c.solicitation_procedure)
        )
        latest = self._fetch(
            select(
                t.c.reference_number,
                t.c.contract_date,
                t.c.department,
                t.c.description_en,
                t.c.solicitation_procedure,
                t.c.committed_value,
            )
            .where(t.c.vendor_key == best["vendor_key"])
            .order_by(desc(t.c.contract_date))
            .limit(self._cap(recent))
        )
        for r in by_dept:
            r["committed_value"] = _money(r["committed_value"])
        for r in by_proc:
            r["value"] = _money(r["value"])
            r["label"] = SOLICITATION_PROCEDURES.get(r["solicitation_procedure"] or "", "Not reported")
        for r in latest:
            r["committed_value"] = _money(r["committed_value"])
        return _envelope(
            "v_vendor_summary, v_contracts",
            {"vendor": vendor},
            [best],
            other_matches=[m["vendor_name"] for m in matches[1:]],
            top_departments=by_dept,
            solicitation_mix=by_proc,
            recent_transactions=latest,
        )

    def spend_breakdown(self, group_by: str, filters: Filters, limit: int = 15) -> dict[str, Any]:
        t = v_spend_by_year
        dim = getattr(t.c, {"year": "contract_year"}.get(group_by, group_by))
        total = func.sum(t.c.committed_value).label("committed_value")
        stmt = select(dim.label(group_by), func.sum(t.c.transaction_count).label("transaction_count"), total)
        stmt = filters.apply(stmt, t).group_by(dim)
        stmt = stmt.order_by(dim if group_by == "year" else desc(total)).limit(self._cap(limit))
        rows = self._fetch(stmt)
        labels = {"commodity_type": COMMODITY_TYPES, "solicitation_procedure": SOLICITATION_PROCEDURES}.get(group_by)
        for r in rows:
            r["committed_value"] = _money(r["committed_value"])
            if labels:
                r["label"] = labels.get(r[group_by] or "", "Not reported")
        return _envelope("v_spend_by_year", {**filters.as_dict(), "group_by": group_by}, rows)

    def competition_summary(self, filters: Filters) -> dict[str, Any]:
        t = v_contracts
        competitive = t.c.solicitation_procedure.in_(COMPETITIVE)
        stmt = select(
            func.count().label("transactions"),
            func.sum(t.c.committed_value).label("committed_value"),
            func.sum(case((competitive, t.c.committed_value), else_=literal(0))).label("competitive_value"),
            func.sum(case((t.c.solicitation_procedure == "TN", t.c.committed_value), else_=literal(0))).label(
                "non_competitive_value"
            ),
            func.sum(case((t.c.solicitation_procedure == "AC", t.c.committed_value), else_=literal(0))).label(
                "acan_value"
            ),
            func.avg(case((competitive & (t.c.number_of_bids > 0), t.c.number_of_bids))).label("avg_bids_competitive"),
        ).where(t.c.instrument_type.is_(None) | (t.c.instrument_type != "A"))
        row = self._fetch(filters.apply(stmt, t))[0]
        total = float(row["committed_value"] or 0)
        for k in ("committed_value", "competitive_value", "non_competitive_value", "acan_value"):
            row[k] = _money(row[k])
        row["avg_bids_competitive"] = (
            None if row["avg_bids_competitive"] is None else round(float(row["avg_bids_competitive"]), 1)
        )
        for k in ("competitive", "non_competitive", "acan"):
            row[f"{k}_share_pct"] = round(100 * float(row[f"{k}_value"] or 0) / total, 1) if total else None
        return _envelope(
            "v_contracts",
            filters.as_dict(),
            [row],
            note="Amendment rows excluded; shares are by original contract value. ACAN is reported separately "
            "from non-competitive (TN).",
        )

    def search_contracts(self, filters: Filters, limit: int = 10) -> dict[str, Any]:
        t = v_contracts
        stmt = select(
            t.c.reference_number,
            t.c.contract_date,
            t.c.vendor_name,
            t.c.department,
            t.c.description_en,
            t.c.commodity_type,
            t.c.solicitation_procedure,
            t.c.instrument_type,
            t.c.committed_value,
        )
        stmt = filters.apply(stmt, t).order_by(desc(t.c.committed_value)).limit(self._cap(limit))
        rows = self._fetch(stmt)
        for r in rows:
            r["committed_value"] = _money(r["committed_value"])
        return _envelope("v_contracts", filters.as_dict(), rows)
