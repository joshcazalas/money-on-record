import csv
import json

from money_on_record_l0.candidates import _load_campaign_entities, _source_rows_url
from money_on_record_l0.contracts import load_inventory


def _write_manifest(root, *, source, operation, artifact) -> None:
    manifests = root / "data" / "manifests"
    manifests.mkdir(parents=True, exist_ok=True)
    payload = {
        "operation": operation,
        "source_slug": source.slug,
        "dataset_id": source.dataset_id,
        "artifact": str(artifact.relative_to(root)),
        "receipt": {"retrieved_at": "2026-08-18T00:00:00+00:00"},
    }
    path = manifests / f"20260818T000000Z-{operation}-{source.slug}-test.json"
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_campaign_loader_admits_only_explicit_entity_rows(tmp_path) -> None:
    source = load_inventory().require("campaign-contributions")
    metadata = tmp_path / "data" / "metadata" / source.dataset_id / "meta.json"
    metadata.parent.mkdir(parents=True)
    metadata.write_text(
        json.dumps(
            {
                "columns": [
                    {"name": "Donor", "fieldName": "donor"},
                    {"name": "Donor_Type", "fieldName": "donor_type"},
                    {"name": "Contribution_Amount", "fieldName": "contribution_amount"},
                ]
            }
        ),
        encoding="utf-8",
    )
    raw = tmp_path / "data" / "raw" / source.dataset_id / "raw.csv"
    raw.parent.mkdir(parents=True)
    with raw.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["Donor", "Donor_Type", "Contribution_Amount"],
        )
        writer.writeheader()
        writer.writerow(
            {"Donor": "Example LLC", "Donor_Type": "ENTITY", "Contribution_Amount": "10"}
        )
        writer.writerow(
            {"Donor": "Example Person", "Donor_Type": "INDIVIDUAL", "Contribution_Amount": "20"}
        )
    _write_manifest(
        tmp_path,
        source=source,
        operation="freeze-metadata",
        artifact=metadata,
    )
    _write_manifest(tmp_path, source=source, operation="acquire-csv", artifact=raw)

    entities = _load_campaign_entities(source, tmp_path)

    assert list(entities) == ["EXAMPLE LLC"]
    assert entities["EXAMPLE LLC"].row_count == 1
    assert entities["EXAMPLE LLC"].amount == 10


def test_source_url_escapes_soql_names() -> None:
    source = load_inventory().require("campaign-contributions")

    url = _source_rows_url(source, {"donor": ["O'Brien & Co"]})

    assert "O%27%27Brien%20%26%20Co" in url
    assert url.startswith("https://data.austintexas.gov/resource/3kfv-biw6.json?")
