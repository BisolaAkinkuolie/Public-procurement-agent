"""Command line entry point: ``procurement-agent <command>``."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from procurement_agent.config import REPO_ROOT, get_settings

SAMPLE_CSV = REPO_ROOT / "data" / "sample" / "contracts_sample.csv"
DOCS_DIR = REPO_ROOT / "data" / "docs"


def cmd_ingest_data(args) -> None:
    from procurement_agent.db.ingest import download, load_csv

    settings = get_settings()
    if args.sample:
        csv_path = SAMPLE_CSV
        print("Loading the SYNTHETIC sample dataset (for demos and tests).")
    elif args.csv:
        csv_path = Path(args.csv)
    else:
        csv_path = REPO_ROOT / "data" / "raw" / "contracts.csv"
        if not csv_path.exists() or args.refresh:
            print(f"Downloading {settings.contracts_csv_url}")
            download(settings.contracts_csv_url, csv_path)
    rows = load_csv(csv_path)
    print(f"Loaded {rows:,} rows into {settings.database_url}")


def cmd_ingest_docs(args) -> None:
    from procurement_agent.llm import OpenAIEmbedder
    from procurement_agent.rag.retriever import build_index, default_store, fetch_all

    docs_dir = Path(args.docs_dir) if args.docs_dir else DOCS_DIR
    if not args.skip_fetch:
        print("Fetching public policy documents...")
        fetch_all(docs_dir)
    n_parents, n_children = build_index(OpenAIEmbedder(), default_store(), docs_dir)
    print(f"Indexed {n_parents} sections as {n_children} chunks.")


def cmd_ask(args) -> None:
    from procurement_agent.runtime import agent_session

    async def run():
        async with agent_session() as agent:
            return await agent.ask(args.question)

    result = asyncio.run(run())
    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
        return
    print(result.answer)
    print(f"\n[{len(result.tool_trace)} tool call(s): {', '.join(t.tool for t in result.tool_trace) or 'none'}]")


def cmd_serve_mcp(args) -> None:
    from procurement_agent.mcp_server.server import main as serve

    serve(http=args.http, host=args.host, port=args.port)


def cmd_serve_api(args) -> None:
    import uvicorn

    uvicorn.run("procurement_agent.api.app:app", host=args.host, port=args.port)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="procurement-agent", description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("ingest-data", help="Load contracts data into the database")
    s.add_argument("--sample", action="store_true", help="Load the small synthetic sample instead")
    s.add_argument("--csv", help="Load a contracts CSV you already downloaded")
    s.add_argument("--refresh", action="store_true", help="Re-download the open dataset")
    s.set_defaults(func=cmd_ingest_data)

    s = sub.add_parser("ingest-docs", help="Fetch policy documents and build the vector index")
    s.add_argument("--skip-fetch", action="store_true", help="Index documents already in the docs folder")
    s.add_argument("--docs-dir", help="Folder of markdown documents to index")
    s.set_defaults(func=cmd_ingest_docs)

    s = sub.add_parser("ask", help="Ask the agent a question")
    s.add_argument("question")
    s.add_argument("--json", action="store_true", help="Print the full result including tool trace")
    s.set_defaults(func=cmd_ask)

    s = sub.add_parser("serve-mcp", help="Run the MCP server (stdio by default)")
    s.add_argument("--http", action="store_true", help="Serve streamable HTTP instead of stdio")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8001)
    s.set_defaults(func=cmd_serve_mcp)

    s = sub.add_parser("serve-api", help="Run the HTTP API and chat page")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    s.set_defaults(func=cmd_serve_api)

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    sys.exit(main())
