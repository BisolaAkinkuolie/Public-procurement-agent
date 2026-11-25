"""Policy retrieval with a relevance floor and section-level citations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from procurement_agent.config import Settings, get_settings
from procurement_agent.llm import Embedder
from procurement_agent.rag import documents
from procurement_agent.rag.chunking import chunk_document
from procurement_agent.rag.sources import POLICY_SOURCES
from procurement_agent.rag.store import LocalVectorStore, VectorStore


@dataclass
class Passage:
    citation: str  # "Directive on the Management of Procurement — 4. Requirements > 4.1 ..."
    url: str
    text: str
    score: float

    def to_dict(self) -> dict:
        return {"citation": self.citation, "url": self.url, "score": round(self.score, 3), "text": self.text}


class PolicyRetriever:
    def __init__(self, embedder: Embedder, store: VectorStore, top_k: int = 5, relevance_floor: float = 0.3):
        self.embedder = embedder
        self.store = store
        self.top_k = top_k
        self.relevance_floor = relevance_floor

    def retrieve(self, query: str) -> list[Passage]:
        qv = self.embedder.embed([query])[0]
        # Over-fetch children, then collapse to distinct parent sections.
        hits = self.store.search(qv, self.top_k * 3)
        passages: list[Passage] = []
        seen: set[str] = set()
        for child, score in hits:
            if score < self.relevance_floor or child.parent_id in seen:
                continue
            parent = self.store.get_parent(child.parent_id)
            if parent is None:
                continue
            seen.add(child.parent_id)
            passages.append(Passage(f"{parent.doc_title} — {parent.section}", parent.url, parent.text, score))
            if len(passages) == self.top_k:
                break
        return passages


def build_index(embedder: Embedder, store: VectorStore, docs_dir: Path) -> tuple[int, int]:
    parents, children = [], []
    for path in sorted(Path(docs_dir).glob("*.md")):
        p, c = chunk_document(documents.load(path))
        parents.extend(p)
        children.extend(c)
    if not children:
        raise RuntimeError(f"No documents found in {docs_dir}. Run `procurement-agent ingest-docs` first.")
    vectors = embedder.embed([c.text for c in children])
    store.upsert(parents, children, vectors)
    return len(parents), len(children)


def fetch_all(docs_dir: Path) -> list[str]:
    fetched = []
    for src in POLICY_SOURCES:
        try:
            documents.fetch(src, docs_dir)
            fetched.append(src.title)
            print(f"  fetched {src.title}")
        except Exception as exc:  # one unreachable page should not stop the others
            print(f"  skipped {src.title}: {exc}")
    return fetched


def default_store(settings: Settings | None = None) -> VectorStore:
    s = settings or get_settings()
    if s.mode == "azure":
        from procurement_agent.rag.store import AzureSearchStore

        if not s.azure_search_endpoint:
            raise ValueError("PA_AZURE_SEARCH_ENDPOINT is required in azure mode")
        return AzureSearchStore(s.azure_search_endpoint, s.azure_search_index)
    return LocalVectorStore(s.index_dir)
