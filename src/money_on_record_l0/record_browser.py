"""Validate the bounded public extracts and render the static record browser."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from .contracts import load_inventory
from .privacy import contains_pii, validate_public_header

ROOT = Path(__file__).resolve().parents[2]
PUBLICATIONS = ("campaign-contributions", "echeckbook", "sources")
PUBLIC_FIELDS = {
    "campaign-contributions": (
        "transaction_id",
        "donor",
        "donor_type",
        "recipient",
        "contribution_date",
        "contribution_amount",
        "contribution_type",
        "correction",
        "view_report",
    ),
    "echeckbook": (
        "lgl_nm",
        "vend_cust_cd",
        "chk_eft_iss_dt",
        "dept_nm",
        "amount",
        "cvl_chk_sta_dv",
        "fy_dc",
        "obj_nm",
        "rfed_doc_cd",
        "rfed_doc_dept_cd",
        "rfed_doc_id",
        "rfed_vend_ln_no",
        "rfed_comm_ln_no",
        "rfed_actg_ln_no",
    ),
}
PUBLIC_FILTERS = {
    "campaign-contributions": {"donor_type": "ENTITY"},
    "echeckbook": {"lgl_nm": "AUSTIN BOARD OF REALTORS", "vend_cust_cd": "AUS6036990"},
}


def source_catalog(root: Path = ROOT) -> list[dict[str, Any]]:
    catalog = []
    for slug, source in load_inventory(root / "config/sources.yaml").sources.items():
        profiles = sorted((root / "reports/profiles").glob(f"*-{slug}.json"))
        profile = json.loads(profiles[-1].read_text(encoding="utf-8"))
        catalog.append(
            {
                "slug": slug,
                "title": source.title,
                "dataset_id": source.dataset_id,
                "row_count": profile["row_count"],
                "profiled_at": profile["created_at"],
                "sha256": Path(profile["artifact"]).stem,
                "url": f"https://data.austintexas.gov/d/{source.dataset_id}",
                "csv_url": source.bulk_csv_url,
                "dates": {
                    field: {"min": value["minimum"], "max": value["maximum"]}
                    for field, value in profile["fields"].items()
                    if field in source.date_fields and value.get("minimum")
                },
            }
        )
    return catalog


def validate_records(document: dict[str, Any], slug: str) -> None:
    expected_keys = {
        "selection_version",
        "sha256",
        "profiled_at",
        "dataset_id",
        "fields",
        "where",
        "rows",
    }
    if set(document) != expected_keys or document["selection_version"] != 1:
        raise ValueError(f"Unsupported publication schema: {slug}")
    fields = PUBLIC_FIELDS[slug]
    source = load_inventory().require(slug)
    validate_public_header(document["fields"], source)
    if document["fields"] != list(fields) or document["where"] != PUBLIC_FILTERS[slug]:
        raise ValueError(f"Publication exceeds the selected fields or filters: {slug}")
    expected = next(item for item in source_catalog() if item["slug"] == slug)
    for field in ("sha256", "profiled_at", "dataset_id"):
        if document[field] != expected[field]:
            raise ValueError(f"Publication source lineage differs: {slug}, {field}")
    rows = document["rows"]
    if not isinstance(rows, list) or not 1 <= len(rows) <= 5000:
        raise ValueError(f"Publication must contain a bounded, nonempty set of records: {slug}")
    identifiers = set()
    date_field, amount_field = (
        ("contribution_date", "contribution_amount")
        if slug == "campaign-contributions"
        else ("chk_eft_iss_dt", "amount")
    )
    for row in rows:
        if not isinstance(row, dict) or set(row) != set(fields):
            raise ValueError(f"Unexpected record fields: {slug}")
        if any(not isinstance(value, str) for value in row.values()):
            raise ValueError(f"Record values must preserve source strings: {slug}")
        if any(contains_pii(value, field=field) for field, value in row.items()):
            raise ValueError(f"Publication failed the privacy scan: {slug}")
        if not all(row[field] == value for field, value in PUBLIC_FILTERS[slug].items()):
            raise ValueError(f"Record outside the selected coverage: {slug}")
        try:
            datetime.strptime(row[date_field].split()[0], "%m/%d/%Y")
            amount = Decimal(row[amount_field])
            if not amount.is_finite() or amount != amount.quantize(Decimal(".01")):
                raise ValueError
        except (ValueError, InvalidOperation) as error:
            raise ValueError(f"Invalid record date or amount: {slug}") from error
        if slug == "campaign-contributions":
            identifier = row["transaction_id"]
            if not identifier or identifier in identifiers:
                raise ValueError("Contribution transaction IDs must be present and unique")
            identifiers.add(identifier)


def load_publications(content_path: Path) -> dict[str, bytes]:
    content = json.loads(content_path.read_text(encoding="utf-8"))
    if set(content) != {"schema_version", "publications"} or content["schema_version"] != 1:
        raise ValueError("Unsupported browser content schema")
    digests = content["publications"]
    if set(digests) != set(PUBLICATIONS):
        raise ValueError("Browser publication set differs from the supported sources")
    files = {}
    for slug in PUBLICATIONS:
        path = content_path.parent / "data" / f"{slug}.json"
        if path.is_symlink() or path.stat().st_size > 2 * 1024 * 1024:
            raise ValueError(f"Publication is not a bounded regular file: {slug}")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != digests[slug]:
            raise ValueError(f"Publication checksum differs: {slug}")
        document = json.loads(raw)
        if slug == "sources":
            if document != source_catalog():
                raise ValueError("Source directory differs from the frozen source profiles")
        else:
            validate_records(document, slug)
        files[f"_data/{slug}.json"] = raw
    return files


def render_browser(content_path: Path) -> tuple[dict[str, bytes], list[str]]:
    files = load_publications(content_path)
    frontend = ROOT / "frontend"

    def asset(name: str, text: str | None = None) -> str:
        data = (frontend / name).read_bytes() if text is None else text.encode()
        path = Path(name)
        hashed = f"assets/{path.stem}-{hashlib.sha256(data).hexdigest()[:16]}{path.suffix}"
        files[hashed] = data
        return f"/{hashed}"

    css = asset("styles.css")
    icon = asset("favicon.svg")
    logic = asset("data.js")
    app = asset("app.js", (frontend / "app.js").read_text().replace('"./data.js"', f'"{logic}"'))
    index = (frontend / "index.html").read_text(encoding="utf-8")
    index = index.replace("./styles.css", css).replace("./favicon.svg", icon)
    index = index.replace("./app.js", app)
    index = re.sub(r'^.*<script[^>]*src="./dev-reload.js"[^>]*></script>\n', "", index, flags=re.M)
    index = index.replace(">Local preview</span>", ">Research beta</span>")
    files["index.html"] = index.encode()
    not_found = re.sub(
        r'<div id="app">.*?</div>',
        '<div id="app"><h1>Page not found</h1><p><a href="/">Browse the records</a></p></div>',
        index,
        flags=re.S,
    )
    not_found = re.sub(r"^.*<script.*?</script>\n", "", not_found, flags=re.M)
    not_found = not_found.replace("<title>Campaign contributions", "<title>Page not found")
    not_found = not_found.replace('href="#/', 'href="/#/')
    files["404.html"] = not_found.encode()
    # Preserve the former profile URL with direct links into the replacement browser.
    moved = not_found.replace("Page not found", "Austin Board of REALTORS records")
    moved = moved.replace(
        '<p><a href="/">Browse the records</a></p>',
        "<p>This profile has moved into the record browser.</p>"
        '<p><a href="/#/contributions?q=Austin+Board+of+REALTORS">Contribution records</a></p>'
        '<p><a href="/#/payments">City payment records</a></p>'
        "<p>The identity link between these sources remains unverified.</p>",
    )
    files["profiles/austin-board-of-realtors/index.html"] = moved.encode()
    files["robots.txt"] = b"User-agent: *\nDisallow: /\n"
    return files, sorted(item["sha256"] for item in source_catalog())
