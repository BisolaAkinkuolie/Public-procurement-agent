from procurement_agent.rag import documents
from procurement_agent.rag.chunking import chunk_document
from tests.conftest import FIXTURE_DOCS


def test_chunks_follow_document_headings():
    doc = documents.load(FIXTURE_DOCS / "sample-procurement-directive.md")
    parents, children = chunk_document(doc)
    sections = [p.section for p in parents]
    assert "Sample Procurement Directive > 2. Competition > 2.2 Exceptions to competition" in sections
    assert all(c.parent_id in {p.id for p in parents} for c in children)
    assert all(c.text.startswith("Sample Procurement Directive") for c in children)


def test_long_sections_split_into_bounded_parents():
    body = " ".join(f"Sentence number {i} about procurement rules." for i in range(400))
    doc = documents.Document("long", "Long Doc", "https://example.org", "test", f"# Long\n\n{body}")
    parents, children = chunk_document(doc, parent_max_chars=1000, child_chars=300)
    assert len(parents) > 5
    assert max(len(p.text) for p in parents) <= 1100
    assert max(len(c.text) for c in children) <= 300 + len("Long: ") + 60


def test_retrieves_the_relevant_section_with_citation(retriever):
    passages = retriever.retrieve("when can a contract be awarded without competition")
    assert passages
    assert passages[0].citation.endswith("2.2 Exceptions to competition")
    assert passages[0].url == "https://example.org/sample-procurement-directive"


def test_relevance_floor_returns_nothing_for_off_topic_queries(retriever):
    assert retriever.retrieve("quantum chromodynamics on a lattice") == []


def test_html_to_markdown_keeps_structure_and_drops_chrome():
    html = (
        "<html><body><nav>Menu</nav><main><h1>Directive</h1><h2>4. Requirements</h2>"
        "<p>Officials must do X.</p><ul><li>First</li><li><p>Second</p></li></ul></main>"
        "<footer>Footer</footer></body></html>"
    )
    md = documents.html_to_markdown(html)
    assert "Menu" not in md and "Footer" not in md
    assert "## 4. Requirements" in md
    assert "- First" in md and "- Second" in md
