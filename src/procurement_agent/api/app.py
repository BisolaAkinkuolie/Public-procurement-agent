"""HTTP API and a minimal chat page.

procurement-agent serve-api        # http://127.0.0.1:8000
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from procurement_agent import __version__
from procurement_agent.agent.guardrails import MAX_QUESTION_CHARS, GuardrailError
from procurement_agent.runtime import agent_session
from procurement_agent.telemetry import configure

STATIC = Path(__file__).with_name("static")


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)


def create_app(session_factory=agent_session) -> FastAPI:
    configure()
    app = FastAPI(title="Public Procurement Agent", version=__version__)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "version": __version__}

    @app.post("/chat")
    async def chat(req: ChatRequest) -> dict:
        # One MCP session per request keeps requests isolated; the in-process server makes this cheap.
        try:
            async with session_factory() as agent:
                result = await agent.ask(req.question)
        except GuardrailError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return result.to_dict()

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    return app


app = create_app()
