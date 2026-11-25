from __future__ import annotations

from pathlib import Path

import pytest

from procurement_agent.config import Settings
from procurement_agent.db.connection import get_readonly_engine, get_write_engine
from procurement_agent.db.ingest import load_csv
from procurement_agent.llm import HashEmbedder
from procurement_agent.mcp_server.server import build_server
from procurement_agent.rag.retriever import PolicyRetriever, build_index
from procurement_agent.rag.store import LocalVectorStore

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_CSV = ROOT / "data" / "sample" / "contracts_sample.csv"
FIXTURE_DOCS = ROOT / "tests" / "fixtures" / "policy_docs"


@pytest.fixture(scope="session")
def db_url(tmp_path_factory) -> str:
    path = tmp_path_factory.mktemp("db") / "test.db"
    url = f"sqlite:///{path}"
    load_csv(SAMPLE_CSV, get_write_engine(url))
    return url


@pytest.fixture(scope="session")
def ro_engine(db_url):
    return get_readonly_engine(db_url)


@pytest.fixture(scope="session")
def mcp_server(ro_engine):
    return build_server(ro_engine, max_rows=25)


@pytest.fixture(scope="session")
def retriever(tmp_path_factory) -> PolicyRetriever:
    index_dir = tmp_path_factory.mktemp("index")
    build_index(HashEmbedder(), LocalVectorStore(index_dir), FIXTURE_DOCS)
    return PolicyRetriever(HashEmbedder(), LocalVectorStore(index_dir), top_k=3, relevance_floor=0.1)


@pytest.fixture
def settings(db_url, tmp_path) -> Settings:
    return Settings(mode="local", database_url=db_url, index_dir=tmp_path / "index")
