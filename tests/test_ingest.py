import pandas as pd
import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from procurement_agent.db.ingest import normalise_vendor, transform


def test_vendor_names_normalise_across_spelling_variants():
    assert normalise_vendor("Aurora Data Systems Ltd.") == normalise_vendor("AURORA DATA SYSTEMS LTD")
    assert normalise_vendor("Acme Consulting Inc") == "ACME CONSULTING"
    assert normalise_vendor("   ") is None
    assert normalise_vendor(None) is None


def test_committed_value_counts_amendments_once():
    raw = pd.DataFrame(
        {
            "vendor_name": ["A Co", "A Co"],
            "contract_date": ["2024-01-01", "2024-06-01"],
            "contract_value": ["$100,000.00", "130000"],
            "original_value": ["100000", "100000"],
            "amendment_value": ["", "30000"],
            "instrument_type": ["C", "a"],
        }
    )
    out = transform(raw)
    # New contract contributes its original value, amendment contributes only the change.
    assert out["committed_value"].tolist() == [100000.0, 30000.0]
    assert out["contract_year"].tolist() == [2024, 2024]
    assert out["instrument_type"].tolist() == ["C", "A"]


def test_missing_source_columns_are_tolerated():
    out = transform(pd.DataFrame({"vendor_name": ["X Ltd"], "contract_value": ["15000"]}))
    assert out.loc[0, "committed_value"] == 15000.0
    assert pd.isna(out.loc[0, "department"])


def test_standing_offer_agreements_are_excluded_from_views(ro_engine):
    with ro_engine.connect() as conn:
        in_base = conn.execute(text("SELECT COUNT(*) FROM contracts WHERE instrument_type = 'SOSA'")).scalar()
        in_view = conn.execute(text("SELECT COUNT(*) FROM v_contracts WHERE instrument_type = 'SOSA'")).scalar()
    assert in_base == 1 and in_view == 0


def test_views_hide_fields_about_individuals(ro_engine):
    with ro_engine.connect() as conn:
        cols = conn.execute(text("SELECT * FROM v_contracts LIMIT 1")).keys()
    assert "vendor_postal_code" not in cols
    assert "former_public_servant" not in cols


def test_readonly_engine_rejects_writes(ro_engine):
    with ro_engine.connect() as conn, pytest.raises(OperationalError):
        conn.execute(text("DELETE FROM contracts"))
