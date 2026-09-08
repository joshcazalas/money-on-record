"""Prepare minimal, scanned frontend data from the existing frozen City snapshots."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import TypedDict

from money_on_record_l0.contracts import load_inventory
from money_on_record_l0.privacy import contains_pii, validate_public_header
from money_on_record_l0.record_browser import PUBLIC_FIELDS, PUBLIC_FILTERS
from money_on_record_l0.source_schema import resolved_source_header

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "frontend" / "_data"
SELECTION_VERSION = 1


class Selection(TypedDict):
    fields: tuple[str, ...]
    where: dict[str, str]


SELECTIONS: dict[str, Selection] = {
    slug: {"fields": fields, "where": PUBLIC_FILTERS[slug]}
    for slug, fields in PUBLIC_FIELDS.items()
}


def _write_json(path: Path, value: object) -> None:
    """Replace one complete JSON file; never leave a partial download on disk."""
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as handle:
        json.dump(value, handle, ensure_ascii=False, separators=(",", ":"))
        temporary = handle.name
    os.replace(temporary, path)


def build(*, force: bool = False) -> None:
    inventory = load_inventory()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    catalog = []
    for slug, source in inventory.sources.items():
        profiles = sorted((ROOT / "reports" / "profiles").glob(f"*-{slug}.json"))
        if not profiles:
            raise ValueError(f"Missing frozen source profile: {slug}")
        profile = json.loads(profiles[-1].read_text())
        artifact = ROOT / profile["artifact"]
        catalog.append(
            {
                "slug": slug,
                "title": source.title,
                "dataset_id": source.dataset_id,
                "row_count": profile["row_count"],
                "profiled_at": profile["created_at"],
                "sha256": artifact.stem,
                "url": f"https://data.austintexas.gov/d/{source.dataset_id}",
                "csv_url": source.bulk_csv_url,
                "dates": {
                    field: {"min": value["minimum"], "max": value["maximum"]}
                    for field, value in profile["fields"].items()
                    if field in source.date_fields and value.get("minimum")
                },
            }
        )
        if slug not in SELECTIONS:
            continue
        selection = SELECTIONS[slug]
        fields = selection["fields"]
        where = selection["where"]
        destination = OUTPUT / f"{slug}.json"
        if destination.exists() and not force:
            cached = json.loads(destination.read_text())
            if (
                cached.get("selection_version") == SELECTION_VERSION
                and cached.get("sha256") == artifact.stem
            ):
                continue
        if not artifact.is_file():
            raise ValueError(f"Missing local snapshot for {slug}; see frontend/README.md")
        print(f"Preparing {slug} from its frozen snapshot…", flush=True)
        with artifact.open("rb") as handle:
            if hashlib.file_digest(handle, "sha256").hexdigest() != artifact.stem:
                raise ValueError(f"Snapshot checksum mismatch: {slug}")
        validate_public_header(fields, source)
        rows = []
        with artifact.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            header = resolved_source_header(reader.fieldnames or (), source, ROOT)
            for row in reader:
                if not all(row[header[field]] == value for field, value in where.items()):
                    continue
                selected = {field: row[header[field]] for field in fields}
                if any(contains_pii(value, field=field) for field, value in selected.items()):
                    raise ValueError(f"Selected {slug} data failed the privacy scan")
                rows.append(selected)
        _write_json(
            destination,
            {
                "selection_version": SELECTION_VERSION,
                "sha256": artifact.stem,
                "profiled_at": profile["created_at"],
                "dataset_id": source.dataset_id,
                "fields": fields,
                "where": where,
                "rows": rows,
            },
        )
        print(f"Prepared {len(rows):,} {slug} rows.", flush=True)
    _write_json(OUTPUT / "sources.json", catalog)


if __name__ == "__main__":
    build(force=True)
