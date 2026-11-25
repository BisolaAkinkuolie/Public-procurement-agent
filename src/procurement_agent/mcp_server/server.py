"""MCP server exposing governed procurement analytics tools.

Any MCP client can use it: this repo's agent, Claude Desktop, VS Code, or an Azure AI Foundry
agent pointed at the streamable-HTTP endpoint.

    procurement-agent serve-mcp                 # stdio
    procurement-agent serve-mcp --http --port 8001
"""

from __future__ import annotations

from typing import Annotated, Literal

from mcp.server.mcpserver import MCPServer
from pydantic import Field
from sqlalchemy import Engine

from procurement_agent.config import get_settings
from procurement_agent.mcp_server.queries import Filters, ProcurementQueries

Year = Annotated[int, Field(ge=2000, le=2100)]
Text = Annotated[str, Field(min_length=2, max_length=80)]
Limit = Annotated[int, Field(ge=1, le=25)]
Commodity = Literal["G", "S", "C"]

INSTRUCTIONS = (
    "Read-only analytics over Government of Canada contracts over $10,000. Tools return JSON with a "
    "'source' and 'filters' field: cite them. Values are in CAD and include taxes. Never infer wrongdoing "
    "from these figures; non-competitive contracts can be fully legitimate."
)


def build_server(engine: Engine, max_rows: int | None = None) -> MCPServer:
    q = ProcurementQueries(engine, max_rows=max_rows or get_settings().max_rows_per_tool_call)
    server = MCPServer("public-procurement", instructions=INSTRUCTIONS, version="0.1.0")

    @server.tool()
    def describe_data() -> dict:
        """Describe the dataset: date coverage, number of vendors and departments, code lists and how
        contract value is defined. Call this first if unsure what the data contains."""
        return q.describe_data()

    @server.tool()
    def top_vendors(
        keyword: Text | None = None,
        department: Text | None = None,
        commodity_type: Commodity | None = None,
        year_from: Year | None = None,
        year_to: Year | None = None,
        rank_by: Literal["committed_value", "transaction_count"] = "committed_value",
        limit: Limit = 10,
    ) -> dict:
        """Rank vendors by committed contract value or number of transactions.

        keyword filters on the description of work (e.g. 'cloud', 'translation').
        department is a partial, case-insensitive match on the buying department.
        commodity_type: G = goods, S = services, C = construction."""
        f = Filters(department, commodity_type, year_from, year_to, keyword)
        return q.top_vendors(f, rank_by=rank_by, limit=limit)

    @server.tool()
    def vendor_profile(vendor: Text) -> dict:
        """Profile one vendor: total committed value, date range, top buying departments, mix of
        competitive and non-competitive awards, and most recent transactions. Partial names work."""
        return q.vendor_profile(vendor)

    @server.tool()
    def spend_breakdown(
        group_by: Literal["year", "department", "commodity_type", "solicitation_procedure"],
        department: Text | None = None,
        commodity_type: Commodity | None = None,
        year_from: Year | None = None,
        year_to: Year | None = None,
        limit: Limit = 15,
    ) -> dict:
        """Total committed value and transaction count grouped by year, department, commodity type
        or solicitation procedure, with optional filters."""
        f = Filters(department, commodity_type, year_from, year_to)
        return q.spend_breakdown(group_by, f, limit=limit)

    @server.tool()
    def competition_summary(
        department: Text | None = None,
        commodity_type: Commodity | None = None,
        year_from: Year | None = None,
        year_to: Year | None = None,
    ) -> dict:
        """Share of contract value awarded competitively vs non-competitively (and via ACAN), plus the
        average number of bids on competitive contracts."""
        return q.competition_summary(Filters(department, commodity_type, year_from, year_to))

    @server.tool()
    def search_contracts(
        keyword: Text,
        department: Text | None = None,
        year_from: Year | None = None,
        year_to: Year | None = None,
        limit: Limit = 10,
    ) -> dict:
        """Find individual contracts whose description of work matches a keyword, largest first."""
        return q.search_contracts(Filters(department, None, year_from, year_to, keyword), limit=limit)

    return server


def main(http: bool = False, host: str = "127.0.0.1", port: int = 8001) -> None:
    from procurement_agent.db.connection import get_readonly_engine

    server = build_server(get_readonly_engine())
    if http:
        server.run("streamable-http", host=host, port=port)
    else:
        server.run()


if __name__ == "__main__":
    main()
