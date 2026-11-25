"""Generate the SYNTHETIC sample dataset in data/sample/contracts_sample.csv.

Every vendor, department and contract in that file is invented. It uses the real column names of
the open "Contracts over $10,000" dataset so the whole pipeline can be exercised offline (tests,
CI, a quick demo) without downloading the full public file.

    python scripts/make_sample_data.py
"""

from __future__ import annotations

import csv
import random
from datetime import date, timedelta
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "data" / "sample" / "contracts_sample.csv"

DEPARTMENTS = [
    "Department of Coastal Resources",
    "Agency for Digital Services",
    "Northern Infrastructure Office",
    "Department of Public Health Research",
    "National Transport Safety Office",
]

# (vendor name variants, commodity type, economic object code, typical descriptions, value range)
VENDORS = [
    (
        ["Aurora Data Systems Ltd.", "AURORA DATA SYSTEMS LTD"],
        "S",
        "0491",
        ["Cloud data platform support", "Data analytics professional services"],
        (40_000, 900_000),
    ),
    (
        ["Maple Ridge Consulting Inc.", "Maple Ridge Consulting Inc"],
        "S",
        "0499",
        ["Management consulting services", "Procurement process review"],
        (25_000, 400_000),
    ),
    (
        ["Northwind IT Solutions"],
        "S",
        "0473",
        ["Information technology and telecommunications consultants", "Help desk services"],
        (15_000, 300_000),
    ),
    (
        ["Prairie Engineering Group"],
        "S",
        "0421",
        ["Engineering consultants - other", "Bridge inspection services"],
        (50_000, 1_200_000),
    ),
    (
        ["Laurentian Construction Co."],
        "C",
        "1233",
        ["Repair and maintenance of buildings", "Office fit-up construction"],
        (100_000, 2_500_000),
    ),
    (
        ["Boreal Facilities Management Inc."],
        "S",
        "0813",
        ["Janitorial services", "Building maintenance services"],
        (12_000, 250_000),
    ),
    (["Tidewater Office Supply"], "G", "1229", ["Office supplies", "Office furniture"], (10_500, 80_000)),
    (
        ["Kestrel Translation Services"],
        "S",
        "0451",
        ["Translation services", "Interpretation services"],
        (10_500, 60_000),
    ),
    (
        ["Granite Software Inc."],
        "G",
        "1281",
        ["Computer software licences", "Software maintenance and support"],
        (20_000, 700_000),
    ),
    (
        ["Summit Security Services Ltd."],
        "S",
        "0811",
        ["Security guard services", "Physical security assessment"],
        (30_000, 500_000),
    ),
]

PROCEDURES = ["OB", "OB", "OB", "TC", "TC", "ST", "TN", "TN", "AC"]


def main(seed: int = 42, n: int = 400) -> None:
    rng = random.Random(seed)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fields = [
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
    rows = []
    start = date(2021, 1, 1)
    for i in range(n):
        names, ctype, eoc, descs, (lo, hi) = rng.choice(VENDORS)
        dept = rng.choice(DEPARTMENTS)
        proc = rng.choice(PROCEDURES)
        bids = 1 if proc in ("TN", "AC") else rng.randint(2, 9)
        value = round(rng.uniform(lo, hi), 2)
        cdate = start + timedelta(days=rng.randint(0, 5 * 365))
        ref = f"SYN-{cdate.year}-{i:05d}"
        rows.append(
            {
                "reference_number": ref,
                "procurement_id": f"SYN{i:06d}",
                "vendor_name": rng.choice(names),
                "vendor_postal_code": "X0X",
                "contract_date": cdate.isoformat(),
                "economic_object_code": eoc,
                "description_en": rng.choice(descs),
                "contract_value": f"{value:.2f}",
                "original_value": f"{value:.2f}",
                "amendment_value": "",
                "commodity_type": ctype,
                "country_of_vendor": "CA",
                "solicitation_procedure": proc,
                "instrument_type": "C",
                "number_of_bids": str(bids),
                "former_public_servant": "N",
                "owner_org": dept.lower().replace(" ", "-"),
                "owner_org_title": dept,
            }
        )
        # About 1 in 8 contracts gets an amendment row later.
        if rng.random() < 0.125:
            delta = round(value * rng.uniform(0.05, 0.4), 2)
            rows.append(
                {
                    **rows[-1],
                    "reference_number": ref + "-A1",
                    "contract_date": (cdate + timedelta(days=rng.randint(60, 300))).isoformat(),
                    "contract_value": f"{value + delta:.2f}",
                    "amendment_value": f"{delta:.2f}",
                    "instrument_type": "A",
                }
            )
    # One standing offer agreement row, which the views must exclude from spend.
    rows.append(
        {
            **rows[0],
            "reference_number": "SYN-SOSA-1",
            "instrument_type": "SOSA",
            "contract_value": "5000000.00",
            "original_value": "5000000.00",
        }
    )

    with OUT.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} synthetic rows to {OUT}")


if __name__ == "__main__":
    main()
