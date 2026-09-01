from __future__ import annotations

import csv
import hashlib
import json
import shutil
from pathlib import Path

import pytest

from money_on_record_l0.contracts import load_inventory
from money_on_record_l0.publication import PublicationError, build_campaign_publication

ROOT = Path(__file__).resolve().parents[1]


def _write_source(
    root: Path,
    *,
    slug: str,
    dataset_id: str,
    fieldnames: list[str],
    rows: list[dict[str, str]],
) -> Path:
    directory = root / "data" / "raw" / dataset_id
    directory.mkdir(parents=True, exist_ok=True)
    staging = directory / "source.csv"
    with staging.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    digest = hashlib.sha256(staging.read_bytes()).hexdigest()
    artifact = staging.with_name(f"{digest}.csv")
    staging.rename(artifact)
    manifest = {
        "artifact": artifact.relative_to(root).as_posix(),
        "receipt": {"retrieved_at": "2099-01-02T03:04:05+00:00"},
    }
    manifests = root / "data" / "manifests"
    manifests.mkdir(parents=True, exist_ok=True)
    (manifests / f"20990102T030405Z-acquire-csv-{slug}-{digest[:12]}.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    return artifact


def _fixture_root(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    shutil.copytree(ROOT / "data" / "metadata", root / "data" / "metadata")
    manifests = root / "data" / "manifests"
    manifests.mkdir(parents=True)
    for source in (ROOT / "data" / "manifests").glob("*-freeze-metadata-*.json"):
        shutil.copy2(source, manifests / source.name)

    _write_source(
        root,
        slug="campaign-reports",
        dataset_id="b2pc-2s8n",
        fieldnames=["Filer_Name", "Form", "Report_Type", "Office_Held", "Office_Sought"],
        rows=[
            {
                "Filer_Name": "Example, Casey",
                "Form": "COH Candidate /Officeholder Campaign Finance Report",
                "Report_Type": "Semiannual",
                "Office_Held": "None",
                "Office_Sought": "COUNCIL_MBR_DISTRICT_01",
            },
            {
                "Filer_Name": "Example PAC",
                "Form": "GPAC Committee Campaign Finance Report",
                "Report_Type": "Semiannual",
                "Office_Held": "",
                "Office_Sought": "",
            },
        ],
    )
    _write_source(
        root,
        slug="campaign-contributions",
        dataset_id="3kfv-biw6",
        fieldnames=[
            "Donor",
            "Recipient",
            "Contribution_Amount",
            "Contribution_Date",
            "Donor_Type",
            "Contribution_Type",
            "Correction",
            "View_Report",
            "TRANSACTION_ID",
        ],
        rows=[
            {
                "Donor": "One Person",
                "Recipient": "Example, Casey",
                "Contribution_Amount": "125.50",
                "Contribution_Date": "01/02/2026",
                "Donor_Type": "INDIVIDUAL",
                "Contribution_Type": "Monetary Political Contribution",
                "Correction": "",
                "View_Report": "View Report (https://services.austintexas.gov/edims/document.cfm?id=123)",
                "TRANSACTION_ID": "R1-A1",
            },
            {
                "Donor": "Example Business LLC",
                "Recipient": "Example, Casey",
                "Contribution_Amount": "250.00",
                "Contribution_Date": "02/03/2026",
                "Donor_Type": "ENTITY",
                "Contribution_Type": "Monetary Political Contribution",
                "Correction": "X",
                "View_Report": "View Report (https://services.austintexas.gov/edims/document.cfm?id=124)",
                "TRANSACTION_ID": "R2-A1",
            },
            {
                "Donor": "Committee Supporter",
                "Recipient": "Example PAC",
                "Contribution_Amount": "50.00",
                "Contribution_Date": "03/04/2026",
                "Donor_Type": "INDIVIDUAL",
                "Contribution_Type": "Monetary Political Contribution",
                "Correction": "",
                "View_Report": "View Report (https://services.austintexas.gov/edims/document.cfm?id=125)",
                "TRANSACTION_ID": "R3-A1",
            },
            {
                "Donor": "Unassigned Donor",
                "Recipient": "",
                "Contribution_Amount": "10.00",
                "Contribution_Date": "03/05/2026",
                "Donor_Type": "INDIVIDUAL",
                "Contribution_Type": "Monetary Political Contribution",
                "Correction": "",
                "View_Report": "View Report (https://services.austintexas.gov/edims/document.cfm?id=126)",
                "TRANSACTION_ID": "R4-A1",
            },
        ],
    )
    return root


def test_campaign_publication_is_deterministic_and_aggregated(tmp_path: Path) -> None:
    root = _fixture_root(tmp_path)
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"

    build_campaign_publication(load_inventory(), root=root, output=first, sample_limit=1)
    build_campaign_publication(load_inventory(), root=root, output=second, sample_limit=1)

    assert first.read_bytes() == second.read_bytes()
    publication = json.loads(first.read_text(encoding="utf-8"))
    assert publication["raw_row_count"] == 4
    assert publication["published_row_count"] == 3
    assert publication["excluded_blank_recipient_rows"] == 1
    assert publication["campaign_count"] == 2
    assert publication["correction_row_count"] == 1
    candidate = next(
        campaign for campaign in publication["campaigns"] if campaign["name"] == "Example, Casey"
    )
    assert candidate["classification"] == "Candidate or officeholder"
    assert candidate["office_held"] == []
    assert candidate["office_sought"] == ["COUNCIL_MBR_DISTRICT_01"]
    assert candidate["row_count"] == 2
    assert candidate["amount_cents"] == 37550
    assert candidate["sample_records"][0]["correction"] is True


def test_campaign_publication_rejects_sensitive_name_shaped_values(tmp_path: Path) -> None:
    root = _fixture_root(tmp_path)
    contributions = next((root / "data" / "raw" / "3kfv-biw6").glob("*.csv"))
    source = contributions.read_text(encoding="utf-8")
    contributions.write_text(source.replace("One Person", "research@example.org"), encoding="utf-8")

    with pytest.raises(PublicationError, match="prohibited contact"):
        build_campaign_publication(
            load_inventory(), root=root, output=tmp_path / "unsafe.json", sample_limit=1
        )
