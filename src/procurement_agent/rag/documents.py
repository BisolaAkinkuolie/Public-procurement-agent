"""Fetch policy pages and turn them into heading-structured markdown.

Keeping the heading hierarchy matters: it is what lets chunking follow the document's own sections,
and what lets every answer cite "Directive X, section 4.1" rather than "somewhere in a PDF".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

from procurement_agent.rag.sources import PolicySource

HEADINGS = {"h1": "#", "h2": "##", "h3": "###", "h4": "####"}


@dataclass
class Document:
    slug: str
    title: str
    url: str
    publisher: str
    markdown: str


def html_to_markdown(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "aside", "form", "noscript"]):
        tag.decompose()
    root = soup.find("main") or soup.body or soup
    lines: list[str] = []
    for el in root.find_all(["h1", "h2", "h3", "h4", "p", "li", "dt", "dd", "td"]):
        text = re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip()
        if not text:
            continue
        if el.name in HEADINGS:
            lines.append(f"\n{HEADINGS[el.name]} {text}\n")
        elif el.name == "li":
            # Skip list items that only wrap nested paragraphs we will visit anyway.
            if el.find(["p", "ul", "ol"]):
                continue
            lines.append(f"- {text}")
        else:
            if el.find_parent("li") is not None and el.name == "p":
                lines.append(f"- {text}")
            else:
                lines.append(text)
    md = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", md).strip()


def fetch(source: PolicySource, out_dir: Path) -> Document:
    resp = httpx.get(source.url, follow_redirects=True, timeout=60, headers={"User-Agent": "procurement-agent/0.1"})
    resp.raise_for_status()
    md = html_to_markdown(resp.text)
    doc = Document(source.slug, source.title, source.url, source.publisher, md)
    save(doc, out_dir)
    return doc


def save(doc: Document, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{doc.slug}.md"
    header = (
        f"---\ntitle: {doc.title}\nurl: {doc.url}\npublisher: {doc.publisher}\n"
        f"retrieved: {datetime.now(UTC).date().isoformat()}\n---\n\n"
    )
    path.write_text(header + doc.markdown, encoding="utf-8")
    return path


def load(path: Path) -> Document:
    raw = path.read_text(encoding="utf-8")
    meta: dict[str, str] = {}
    body = raw
    if raw.startswith("---"):
        _, front, body = raw.split("---", 2)
        for line in front.strip().splitlines():
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()
    return Document(
        path.stem, meta.get("title", path.stem), meta.get("url", ""), meta.get("publisher", ""), body.strip()
    )
