"""Load the Government of Canada "Contracts over $10,000" open dataset into a SQL database.

Source: Proactive Publication - Contracts, open.canada.ca (Treasury Board of Canada Secretariat).
The full CSV is several hundred MB, so it is streamed to disk and loaded in chunks.

Data decisions (see docs/design-decisions.md for the reasoning):
* ``committed_value`` avoids double counting. A row with instrument_type 'A' is an amendment and
  contributes only its amendment_value; other rows contribute their original value (falling back
  to total contract value when the original is blank).
* ``vendor_key`` normalises vendor names ("ACME CONSULTING INC." == "Acme Consulting Inc") so
  vendor rankings are not split across spelling variants.
* ``contract_year`` is computed here so the views stay portable across SQLite and Azure SQL.
"""

from __future__ import annotations

import re
from pathlib import Path

import httpx
import pandas as pd
from sqlalchemy import Engine, text

from procurement_agent.db.connection import get_write_engine

VIEWS_SQL = Path(__file__).with_name("views.sql")

# Columns we keep from the source file. Anything else in the CSV is ignored.
SOURCE_COLUMNS = [
    "reference_number",
    "procurement_id",
    "vendor_name",
    "vendor_postal_code",
    "contract_date",
    "economic_object_code",
    "description_en",
    "contract_value",
    "original_value",
    "amendment_value",
    "commodity_type",
    "country_of_vendor",
    "solicitation_procedure",
    "instrument_type",
    "number_of_bids",
    "former_public_servant",
    "owner_org",
    "owner_org_title",
]

_LEGAL_SUFFIXES = re.compile(
    r"\b(INCORPORATED|INC|LTD|LIMITED|LTEE|LTÉE|CORP|CORPORATION|CO|COMPANY|LLC|LLP|LP|ULC|PLC)\b\.?"
)


def normalise_vendor(name: object) -> str | None:
    if not isinstance(name, str) or not name.strip():
        return None
    key = name.upper()
    key = re.sub(r"[^\w\s&]", " ", key)
    key = _LEGAL_SUFFIXES.sub(" ", key)
    key = re.sub(r"\s+", " ", key).strip()
    return key or None


def _money(series: pd.Series) -> pd.Series:
    cleaned = series.astype("string").str.replace(r"[$,\s]", "", regex=True)
    return pd.to_numeric(cleaned, errors="coerce")


def transform(chunk: pd.DataFrame) -> pd.DataFrame:
    df = chunk.copy()
    for col in SOURCE_COLUMNS:
        if col not in df.columns:
            df[col] = pd.NA

    for col in ("contract_value", "original_value", "amendment_value"):
        df[col] = _money(df[col])
    df["number_of_bids"] = pd.to_numeric(df["number_of_bids"], errors="coerce").astype("Int64")

    dates = pd.to_datetime(df["contract_date"], errors="coerce")
    df["contract_date"] = dates.dt.strftime("%Y-%m-%d")
    df["contract_year"] = dates.dt.year.astype("Int64")

    for col in ("commodity_type", "solicitation_procedure", "instrument_type"):
        df[col] = df[col].astype("string").str.strip().str.upper()

    is_amendment = df["instrument_type"].eq("A").fillna(False)
    base_value = df["original_value"].fillna(df["contract_value"])
    df["committed_value"] = base_value.where(~is_amendment, df["amendment_value"]).fillna(0.0)

    df["department"] = df["owner_org_title"].fillna(df["owner_org"])
    df["vendor_key"] = df["vendor_name"].map(normalise_vendor)

    keep = [
        "reference_number",
        "procurement_id",
        "vendor_name",
        "vendor_key",
        "vendor_postal_code",
        "department",
        "contract_date",
        "contract_year",
        "description_en",
        "commodity_type",
        "economic_object_code",
        "solicitation_procedure",
        "instrument_type",
        "number_of_bids",
        "contract_value",
        "original_value",
        "amendment_value",
        "committed_value",
        "country_of_vendor",
        "former_public_servant",
    ]
    return df[keep]


def download(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part")
    with httpx.stream("GET", url, follow_redirects=True, timeout=120) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("content-length", 0))
        done = 0
        with tmp.open("wb") as fh:
            for block in resp.iter_bytes(1 << 20):
                fh.write(block)
                done += len(block)
                if total:
                    print(f"\r  downloaded {done / 1e6:,.0f} / {total / 1e6:,.0f} MB", end="", flush=True)
    print()
    tmp.replace(dest)
    return dest


def create_views(engine: Engine) -> None:
    statements = [s.strip() for s in VIEWS_SQL.read_text().split(";")]
    with engine.begin() as conn:
        for stmt in statements:
            body = "\n".join(line for line in stmt.splitlines() if not line.strip().startswith("--"))
            if body.strip():
                conn.execute(text(body))


def load_csv(csv_path: Path, engine: Engine | None = None, chunksize: int = 100_000) -> int:
    engine = engine or get_write_engine()
    header = pd.read_csv(csv_path, nrows=0, encoding="utf-8-sig").columns
    usecols = [c for c in SOURCE_COLUMNS if c in header]

    with engine.begin() as conn:
        conn.execute(text("DROP VIEW IF EXISTS v_contracts"))
        conn.execute(text("DROP VIEW IF EXISTS v_vendor_summary"))
        conn.execute(text("DROP VIEW IF EXISTS v_spend_by_year"))
        conn.execute(text("DROP TABLE IF EXISTS contracts"))

    rows = 0
    reader = pd.read_csv(
        csv_path, usecols=usecols, dtype=str, chunksize=chunksize, encoding="utf-8-sig", low_memory=False
    )
    for chunk in reader:
        out = transform(chunk)
        out.to_sql("contracts", engine, if_exists="append", index=False, chunksize=5_000)
        rows += len(out)
        print(f"\r  loaded {rows:,} rows", end="", flush=True)
    print()

    # The table was just recreated, so plain CREATE INDEX is safe on every dialect.
    with engine.begin() as conn:
        for col in ("vendor_key", "contract_year", "department"):
            conn.execute(text(f"CREATE INDEX ix_contracts_{col} ON contracts ({col})"))
    create_views(engine)
    return rows
