"""Runtime configuration.

One switch, ``PA_MODE``, decides where the model, the vector index and the database live:

* ``local``: any OpenAI-compatible endpoint (OpenAI, or Ollama on localhost), SQLite and an
  on-disk numpy vector index. Anyone can clone the repo and run it.
* ``azure``: Azure OpenAI, Azure AI Search and Azure SQL, authenticated with Microsoft Entra ID
  (managed identity in Azure, your ``az login`` session on a laptop). No keys are required.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PA_", env_file=".env", extra="ignore")

    mode: Literal["local", "azure"] = "local"

    # --- Models -------------------------------------------------------------------------------
    chat_model: str = "gpt-4o-mini"
    embedding_model: str = "text-embedding-3-small"
    # Local mode: any OpenAI-compatible server. For Ollama use http://localhost:11434/v1
    openai_base_url: str | None = None
    openai_api_key: str | None = Field(default=None, repr=False)
    # Azure mode
    azure_openai_endpoint: str | None = None
    azure_openai_api_version: str = "2024-10-21"
    azure_chat_deployment: str | None = None
    azure_embedding_deployment: str | None = None

    # --- Data ---------------------------------------------------------------------------------
    database_url: str = f"sqlite:///{REPO_ROOT / 'data' / 'procurement.db'}"
    contracts_csv_url: str = (
        "https://open.canada.ca/data/dataset/d8f85d91-7dec-4fd1-8055-483b77225d8b/"
        "resource/fac950c0-00d5-4ec1-a4d3-9cbebf98a305/download/contracts.csv"
    )

    # --- Retrieval ----------------------------------------------------------------------------
    index_dir: Path = REPO_ROOT / "data" / "index"
    azure_search_endpoint: str | None = None
    azure_search_index: str = "procurement-policy"
    retrieval_top_k: int = 5
    # Child chunks scoring below this cosine similarity are dropped. An empty result is better
    # than a confidently cited irrelevant passage.
    relevance_floor: float = 0.30

    # --- Agent --------------------------------------------------------------------------------
    # Leave unset to run the MCP server in-process; set to e.g. http://mcp:8001/mcp to use a
    # separately deployed MCP server.
    mcp_url: str | None = None
    max_agent_steps: int = 6
    max_rows_per_tool_call: int = 25

    # --- Observability ------------------------------------------------------------------------
    applicationinsights_connection_string: str | None = Field(
        default=None, validation_alias="APPLICATIONINSIGHTS_CONNECTION_STRING", repr=False
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
