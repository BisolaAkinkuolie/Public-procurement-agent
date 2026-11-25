"""Model access behind two small interfaces, so the agent never knows which provider it is using.

Azure OpenAI, OpenAI and Ollama all speak the Chat Completions and Embeddings APIs, so one
OpenAI SDK client covers all three. Tests use the fakes at the bottom of this module.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

import numpy as np

from procurement_agent.config import Settings, get_settings


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str  # JSON string, exactly as the model produced it


@dataclass
class ChatResponse:
    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)


class ChatModel(Protocol):
    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> ChatResponse: ...


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> np.ndarray: ...


def _build_client(settings: Settings):
    from openai import AzureOpenAI, OpenAI

    if settings.mode == "azure":
        if not settings.azure_openai_endpoint:
            raise ValueError("PA_AZURE_OPENAI_ENDPOINT is required in azure mode")
        from azure.identity import DefaultAzureCredential, get_bearer_token_provider

        token_provider = get_bearer_token_provider(
            DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default"
        )
        return AzureOpenAI(
            azure_endpoint=settings.azure_openai_endpoint,
            api_version=settings.azure_openai_api_version,
            azure_ad_token_provider=token_provider,
        )
    # Ollama ignores the key but the SDK insists on one.
    return OpenAI(base_url=settings.openai_base_url, api_key=settings.openai_api_key or "not-needed")


class OpenAIChatModel:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.client = _build_client(self.settings)
        self.model = self.settings.azure_chat_deployment if self.settings.mode == "azure" else self.settings.chat_model

    def chat(self, messages, tools=None) -> ChatResponse:
        kwargs: dict[str, Any] = {"model": self.model, "messages": messages}
        if tools:
            kwargs["tools"] = tools
        msg = self.client.chat.completions.create(**kwargs).choices[0].message
        calls = [
            ToolCall(id=c.id, name=c.function.name, arguments=c.function.arguments or "{}")
            for c in (msg.tool_calls or [])
        ]
        return ChatResponse(content=msg.content, tool_calls=calls)


class OpenAIEmbedder:
    def __init__(self, settings: Settings | None = None, batch_size: int = 64):
        self.settings = settings or get_settings()
        self.client = _build_client(self.settings)
        self.model = (
            self.settings.azure_embedding_deployment if self.settings.mode == "azure" else self.settings.embedding_model
        )
        self.batch_size = batch_size

    def embed(self, texts: list[str]) -> np.ndarray:
        vectors: list[list[float]] = []
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i : i + self.batch_size]
            resp = self.client.embeddings.create(model=self.model, input=batch)
            vectors.extend(d.embedding for d in resp.data)
        return _normalise(np.asarray(vectors, dtype=np.float32))


def _normalise(m: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return m / norms


# --- Test doubles ---------------------------------------------------------------------------------


class HashEmbedder:
    """Deterministic bag-of-words embedder. No network, good enough to test retrieval plumbing."""

    def __init__(self, dim: int = 512):
        self.dim = dim

    def embed(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for row, text in enumerate(texts):
            for token in re.findall(r"[a-z0-9]+", text.lower()):
                if len(token) < 3:
                    continue
                h = int(hashlib.md5(token.encode()).hexdigest(), 16)
                out[row, h % self.dim] += 1.0
        return _normalise(out)


class ScriptedChatModel:
    """Replays a fixed list of responses. Lets tests drive the agent loop without a model."""

    def __init__(self, responses: list[ChatResponse]):
        self.responses = list(responses)
        self.calls: list[list[dict[str, Any]]] = []

    def chat(self, messages, tools=None) -> ChatResponse:
        self.calls.append([dict(m) for m in messages])
        if not self.responses:
            raise RuntimeError("ScriptedChatModel ran out of responses")
        return self.responses.pop(0)
