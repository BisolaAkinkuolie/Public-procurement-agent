"""Parent/child chunking.

Small *child* chunks are what gets embedded and matched, because short passages give sharper
similarity scores. The larger *parent* section is what gets handed to the model, because a
requirement read without its surrounding section is easy to misread. Each child points at its
parent, and each parent carries its heading path for citation.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass

from procurement_agent.rag.documents import Document


@dataclass
class Parent:
    id: str
    doc_slug: str
    doc_title: str
    url: str
    section: str  # heading path, e.g. "4. Requirements > 4.1 Senior designated official"
    text: str


@dataclass
class Child:
    id: str
    parent_id: str
    text: str

    def to_dict(self) -> dict:
        return asdict(self)


def _id(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:16]


def split_sections(doc: Document) -> list[tuple[str, str]]:
    """Return (heading path, body) pairs following the markdown heading hierarchy."""
    path: list[tuple[int, str]] = []
    sections: list[tuple[str, str]] = []
    buf: list[str] = []

    def flush():
        body = "\n".join(buf).strip()
        if body:
            heading = " > ".join(h for _, h in path) or doc.title
            sections.append((heading, body))
        buf.clear()

    for line in doc.markdown.splitlines():
        m = re.match(r"^(#{1,4})\s+(.*)$", line)
        if m:
            flush()
            level = len(m.group(1))
            path[:] = [p for p in path if p[0] < level]
            path.append((level, m.group(2).strip()))
        else:
            buf.append(line)
    flush()
    return sections


def _windows(text: str, size: int, overlap: int) -> list[str]:
    sentences = re.split(r"(?<=[.;:])\s+|\n+", text)
    out: list[str] = []
    cur = ""
    for s in sentences:
        s = s.strip()
        if not s:
            continue
        if cur and len(cur) + len(s) + 1 > size:
            out.append(cur)
            cur = cur[-overlap:] + " " + s if overlap else s
        else:
            cur = f"{cur} {s}".strip()
    if cur:
        out.append(cur)
    return out


def chunk_document(
    doc: Document, parent_max_chars: int = 2400, child_chars: int = 600, child_overlap: int = 100
) -> tuple[list[Parent], list[Child]]:
    parents: list[Parent] = []
    children: list[Child] = []
    for heading, body in split_sections(doc):
        # Very long sections are split into several parents so the model's context stays bounded.
        for i, part in enumerate(_windows(body, parent_max_chars, 0)):
            pid = _id(doc.slug, heading, str(i))
            parents.append(Parent(pid, doc.slug, doc.title, doc.url, heading, part))
            for j, piece in enumerate(_windows(part, child_chars, child_overlap)):
                # Prefix the heading so a child like "This applies to all contracts." is still findable.
                children.append(Child(_id(pid, str(j)), pid, f"{heading}: {piece}"))
    return parents, children
