"""Vector stores: an on-disk numpy index for local mode, Azure AI Search for azure mode.

Both store child chunks with their vectors; parents are kept alongside so the retriever can
expand a matched child to its full section.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Protocol

import numpy as np

from procurement_agent.rag.chunking import Child, Parent


class VectorStore(Protocol):
    def upsert(self, parents: list[Parent], children: list[Child], vectors: np.ndarray) -> None: ...
    def search(self, query_vector: np.ndarray, k: int) -> list[tuple[Child, float]]: ...
    def get_parent(self, parent_id: str) -> Parent | None: ...


class LocalVectorStore:
    """Exact cosine search over normalised vectors. Plenty for a few thousand policy chunks."""

    def __init__(self, index_dir: Path):
        self.dir = Path(index_dir)
        self.children: list[Child] = []
        self.parents: dict[str, Parent] = {}
        self.vectors = np.zeros((0, 0), dtype=np.float32)
        if (self.dir / "vectors.npy").exists():
            self._load()

    def upsert(self, parents, children, vectors) -> None:
        self.parents = {p.id: p for p in parents}
        self.children = list(children)
        self.vectors = vectors.astype(np.float32)
        self._save()

    def search(self, query_vector, k):
        if not self.children:
            return []
        scores = self.vectors @ query_vector.astype(np.float32)
        top = np.argsort(-scores)[:k]
        return [(self.children[i], float(scores[i])) for i in top]

    def get_parent(self, parent_id):
        return self.parents.get(parent_id)

    def _save(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        np.save(self.dir / "vectors.npy", self.vectors)
        with (self.dir / "children.jsonl").open("w", encoding="utf-8") as fh:
            for c in self.children:
                fh.write(json.dumps(asdict(c)) + "\n")
        with (self.dir / "parents.jsonl").open("w", encoding="utf-8") as fh:
            for p in self.parents.values():
                fh.write(json.dumps(asdict(p)) + "\n")

    def _load(self) -> None:
        self.vectors = np.load(self.dir / "vectors.npy")
        with (self.dir / "children.jsonl").open(encoding="utf-8") as fh:
            self.children = [Child(**json.loads(line)) for line in fh]
        with (self.dir / "parents.jsonl").open(encoding="utf-8") as fh:
            self.parents = {p.id: p for p in (Parent(**json.loads(line)) for line in fh)}


class AzureSearchStore:
    """Azure AI Search index with an HNSW vector field. Auth via Entra ID (no admin keys)."""

    def __init__(self, endpoint: str, index_name: str, dimensions: int = 1536):
        from azure.identity import DefaultAzureCredential
        from azure.search.documents import SearchClient
        from azure.search.documents.indexes import SearchIndexClient

        cred = DefaultAzureCredential()
        self.index_name = index_name
        self.dimensions = dimensions
        self.index_client = SearchIndexClient(endpoint, cred)
        self.client = SearchClient(endpoint, index_name, cred)

    def _ensure_index(self) -> None:
        from azure.search.documents.indexes.models import (
            HnswAlgorithmConfiguration,
            SearchableField,
            SearchField,
            SearchFieldDataType,
            SearchIndex,
            SimpleField,
            VectorSearch,
            VectorSearchProfile,
        )

        fields = [
            SimpleField(name="id", type=SearchFieldDataType.String, key=True),
            SimpleField(name="kind", type=SearchFieldDataType.String, filterable=True),
            SimpleField(name="parent_id", type=SearchFieldDataType.String, filterable=True),
            SimpleField(name="doc_slug", type=SearchFieldDataType.String, filterable=True),
            SimpleField(name="doc_title", type=SearchFieldDataType.String),
            SimpleField(name="url", type=SearchFieldDataType.String),
            SearchableField(name="section", type=SearchFieldDataType.String),
            SearchableField(name="text", type=SearchFieldDataType.String),
            SearchField(
                name="vector",
                type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
                searchable=True,
                vector_search_dimensions=self.dimensions,
                vector_search_profile_name="hnsw-profile",
            ),
        ]
        vector_search = VectorSearch(
            algorithms=[HnswAlgorithmConfiguration(name="hnsw")],
            profiles=[VectorSearchProfile(name="hnsw-profile", algorithm_configuration_name="hnsw")],
        )
        self.index_client.create_or_update_index(
            SearchIndex(name=self.index_name, fields=fields, vector_search=vector_search)
        )

    def upsert(self, parents, children, vectors) -> None:
        self._ensure_index()
        docs = [{"id": p.id, "kind": "parent", **{k: v for k, v in asdict(p).items() if k != "id"}} for p in parents]
        by_parent = {p.id: p for p in parents}
        for c, v in zip(children, vectors, strict=True):
            p = by_parent[c.parent_id]
            docs.append(
                {
                    "id": c.id,
                    "kind": "child",
                    "parent_id": c.parent_id,
                    "doc_slug": p.doc_slug,
                    "doc_title": p.doc_title,
                    "url": p.url,
                    "section": p.section,
                    "text": c.text,
                    "vector": v.tolist(),
                }
            )
        for i in range(0, len(docs), 500):
            self.client.merge_or_upload_documents(docs[i : i + 500])

    def search(self, query_vector, k):
        from azure.search.documents.models import VectorizedQuery

        results = self.client.search(
            search_text=None,
            vector_queries=[VectorizedQuery(vector=query_vector.tolist(), k_nearest_neighbors=k, fields="vector")],
            filter="kind eq 'child'",
            select=["id", "parent_id", "text"],
            top=k,
        )
        # Azure AI Search reports cosine similarity as 1 / (1 + distance) style scores; convert back so
        # the same relevance floor works in both modes.
        out = []
        for r in results:
            score = float(r["@search.score"])
            cosine = 2 - 1 / score if score > 0 else -1.0
            out.append((Child(r["id"], r["parent_id"], r["text"]), cosine))
        return out

    def get_parent(self, parent_id):
        try:
            d = self.client.get_document(parent_id)
        except Exception:
            return None
        return Parent(d["id"], d["doc_slug"], d["doc_title"], d["url"], d["section"], d["text"])
