"""Database engines.

The agent only ever gets a *read-only* engine. Writes happen in a separate ingest step with a
separate engine, which mirrors the production split between a pipeline identity that loads data
and an agent identity that can only SELECT from approved views.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, create_engine, event

from procurement_agent.config import get_settings


def _sqlite_path(url: str) -> Path | None:
    prefix = "sqlite:///"
    return Path(url[len(prefix) :]) if url.startswith(prefix) else None


def get_write_engine(database_url: str | None = None) -> Engine:
    url = database_url or get_settings().database_url
    path = _sqlite_path(url)
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(url)


def get_readonly_engine(database_url: str | None = None) -> Engine:
    url = database_url or get_settings().database_url
    path = _sqlite_path(url)
    if path is None:
        # Azure SQL: read-only access is enforced by the database login itself (SELECT on the
        # approved views only; see infra/sql/agent_reader.sql), with ApplicationIntent=ReadOnly
        # expected in the connection string.
        return create_engine(url, pool_pre_ping=True)

    if not path.exists():
        raise FileNotFoundError(
            f"No database at {path}. Run `procurement-agent ingest-data --sample` (or without --sample "
            "for the full open dataset) first."
        )
    engine = create_engine(f"sqlite:///file:{path}?mode=ro&uri=true")

    @event.listens_for(engine, "connect")
    def _query_only(dbapi_conn, _record):  # belt and braces on top of mode=ro
        dbapi_conn.execute("PRAGMA query_only = ON")

    return engine
