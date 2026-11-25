import json
import re

import pytest
from mcp.client import Client
from sqlalchemy import event

EXPECTED_TOOLS = {
    "describe_data",
    "top_vendors",
    "vendor_profile",
    "spend_breakdown",
    "competition_summary",
    "search_contracts",
}


async def call(server, name, args=None):
    async with Client(server) as c:
        r = await c.call_tool(name, args or {})
    text = r.content[0].text
    return r.is_error, (text if r.is_error else json.loads(text))


async def test_lists_expected_tools(mcp_server):
    async with Client(mcp_server) as c:
        names = {t.name for t in (await c.list_tools()).tools}
    assert names == EXPECTED_TOOLS


async def test_describe_data(mcp_server):
    err, out = await call(mcp_server, "describe_data")
    assert not err
    assert out["coverage"]["vendors"] == 10
    assert set(out["approved_views"]) == {"v_contracts", "v_vendor_summary", "v_spend_by_year"}


async def test_top_vendors_respects_filters_and_carries_provenance(mcp_server):
    err, out = await call(mcp_server, "top_vendors", {"commodity_type": "G", "limit": 3})
    assert not err
    assert out["filters"]["commodity_type"] == "G"
    assert "open.canada.ca" in out["source"]
    names = {r["vendor_name"] for r in out["rows"]}
    assert names <= {"Tidewater Office Supply", "Granite Software Inc."}
    values = [r["committed_value"] for r in out["rows"]]
    assert values == sorted(values, reverse=True)


async def test_vendor_profile_merges_name_variants(mcp_server):
    err, out = await call(mcp_server, "vendor_profile", {"vendor": "aurora data"})
    assert not err
    assert out["rows"][0]["vendor_key"] == "AURORA DATA SYSTEMS"
    assert out["top_departments"] and out["recent_transactions"]


async def test_vendor_profile_unknown_vendor(mcp_server):
    err, out = await call(mcp_server, "vendor_profile", {"vendor": "No Such Vendor"})
    assert not err and out["rows"] == []


async def test_competition_shares_add_up(mcp_server):
    err, out = await call(mcp_server, "competition_summary", {})
    row = out["rows"][0]
    total = row["competitive_share_pct"] + row["non_competitive_share_pct"] + row["acan_share_pct"]
    assert total == pytest.approx(100, abs=0.2)


async def test_spend_breakdown_by_year_is_chronological(mcp_server):
    err, out = await call(mcp_server, "spend_breakdown", {"group_by": "year"})
    years = [r["year"] for r in out["rows"]]
    assert years == sorted(years)


@pytest.mark.parametrize(
    "args",
    [
        {"limit": 500},
        {"commodity_type": "X"},
        {"year_from": 1500},
        {"rank_by": "DROP TABLE contracts"},
        {"department": "x" * 500},
    ],
)
async def test_invalid_arguments_are_rejected(mcp_server, args):
    err, _ = await call(mcp_server, "top_vendors", args)
    assert err


async def test_sql_injection_is_inert(mcp_server):
    err, out = await call(mcp_server, "search_contracts", {"keyword": "%' OR 1=1 --"})
    assert not err and out["rows"] == []


async def test_tools_only_touch_approved_views(mcp_server, ro_engine):
    seen: list[str] = []

    def capture(conn, cursor, statement, *a):
        seen.append(statement)

    event.listen(ro_engine, "before_cursor_execute", capture)
    try:
        await call(mcp_server, "describe_data")
        await call(mcp_server, "top_vendors", {"keyword": "data"})
        await call(mcp_server, "vendor_profile", {"vendor": "Prairie"})
        await call(mcp_server, "spend_breakdown", {"group_by": "department"})
        await call(mcp_server, "competition_summary", {"year_from": 2022})
        await call(mcp_server, "search_contracts", {"keyword": "security"})
    finally:
        event.remove(ro_engine, "before_cursor_execute", capture)

    assert seen
    for sql in seen:
        tables = set(re.findall(r"\b(?:FROM|JOIN)\s+(\w+)", sql, flags=re.I))
        assert tables <= {"v_contracts", "v_vendor_summary", "v_spend_by_year"}, sql
