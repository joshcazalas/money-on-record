from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode, urlparse

from .acquire import latest_artifact, project_root
from .contracts import Inventory
from .normalize import strict_name_key
from .privacy import contains_pii
from .source_schema import resolved_source_header

CAMPAIGN_PUBLICATION_SCHEMA_VERSION = 1
DEFAULT_SAMPLE_LIMIT = 100
_REPORT_LINK = re.compile(r"^View Report \((https://[^)]+)\)$")
_SOURCE_NULLS = {"", "N/A", "NONE", "NOT APPLICABLE", "NOT REPORTED", "UNKNOWN"}


class PublicationError(ValueError):
    """A source snapshot cannot be converted into a safe public campaign dataset."""


@dataclass(frozen=True)
class Contribution:
    amount_cents: int
    correction: bool
    date: str
    donor: str
    donor_type: str
    report_url: str
    transaction_id: str
    type: str


@dataclass
class FilerFacts:
    forms: set[str] = field(default_factory=set)
    office_held: set[str] = field(default_factory=set)
    office_sought: set[str] = field(default_factory=set)


def _manifest_for_artifact(root: Path, artifact: Path) -> dict[str, Any]:
    expected = artifact.relative_to(root).as_posix()
    matches: list[dict[str, Any]] = []
    for path in (root / "data" / "manifests").glob("*-acquire-csv-*.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("artifact") == expected:
            matches.append(payload)
    if not matches:
        raise PublicationError(f"no acquisition manifest references {expected}")
    return max(matches, key=lambda payload: payload["receipt"]["retrieved_at"])


def _text(value: str, field_name: str) -> str:
    text = value.strip()
    if not text:
        raise PublicationError(f"{field_name} is empty")
    if contains_pii(text, field=field_name):
        raise PublicationError(f"{field_name} contains a prohibited contact or address pattern")
    return text


def _date(value: str) -> str:
    try:
        return datetime.strptime(value.strip(), "%m/%d/%Y").date().isoformat()
    except ValueError as error:
        raise PublicationError("contribution_date is not MM/DD/YYYY") from error


def _amount_cents(value: str) -> int:
    try:
        amount = Decimal(value.replace("$", "").replace(",", "").strip())
    except InvalidOperation as error:
        raise PublicationError("contribution_amount is not decimal currency") from error
    cents = amount * 100
    if cents != cents.to_integral_value() or cents < 0:
        raise PublicationError("contribution_amount must be non-negative cents")
    return int(cents)


def _report_url(value: str) -> str:
    match = _REPORT_LINK.fullmatch(value.strip())
    if match is None:
        raise PublicationError("view_report does not contain an exact filing URL")
    url = match.group(1)
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "services.austintexas.gov"
        or parsed.path != "/edims/document.cfm"
        or not parsed.query.startswith("id=")
        or not parsed.query.removeprefix("id=").isdigit()
        or parsed.fragment
    ):
        raise PublicationError("view_report contains an unsupported filing URL")
    return url


def _load_filer_facts(
    inventory: Inventory, root: Path
) -> tuple[dict[str, FilerFacts], dict[str, Any]]:
    source = inventory.require("campaign-reports")
    artifact = latest_artifact(source, "acquire-csv", root)
    manifest = _manifest_for_artifact(root, artifact)
    facts: dict[str, FilerFacts] = defaultdict(FilerFacts)
    with artifact.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise PublicationError("campaign-reports is missing a CSV header")
        header = resolved_source_header(reader.fieldnames, source, root)
        required = {"filer_name", "form_type", "report_type", "office_held", "office_sought"}
        if missing := sorted(required - header.keys()):
            raise PublicationError(f"campaign-reports is missing fields: {', '.join(missing)}")
        for row in reader:
            filer = row[header["filer_name"]].strip()
            if not filer:
                continue
            key = strict_name_key(filer)
            if not key:
                continue
            item = facts[key]
            for target, canonical in (
                (item.forms, "form_type"),
                (item.forms, "report_type"),
                (item.office_held, "office_held"),
                (item.office_sought, "office_sought"),
            ):
                value = row[header[canonical]].strip()
                if value.upper() not in _SOURCE_NULLS:
                    target.add(_text(value, canonical))
    return dict(facts), _source_manifest(
        source.slug, source.dataset_id, source.title, artifact, manifest
    )


def _load_contributions(
    inventory: Inventory, root: Path
) -> tuple[list[tuple[str, Contribution]], int, dict[str, Any]]:
    source = inventory.require("campaign-contributions")
    artifact = latest_artifact(source, "acquire-csv", root)
    manifest = _manifest_for_artifact(root, artifact)
    records: list[tuple[str, Contribution]] = []
    excluded_blank_recipient_rows = 0
    transaction_ids: set[str] = set()
    with artifact.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise PublicationError("campaign-contributions is missing a CSV header")
        header = resolved_source_header(reader.fieldnames, source, root)
        required = {
            "transaction_id",
            "donor",
            "donor_type",
            "recipient",
            "contribution_date",
            "contribution_amount",
            "contribution_type",
            "correction",
            "view_report",
        }
        if missing := sorted(required - header.keys()):
            raise PublicationError(
                f"campaign-contributions is missing fields: {', '.join(missing)}"
            )
        for row in reader:
            recipient = row[header["recipient"]].strip()
            if not recipient:
                excluded_blank_recipient_rows += 1
                continue
            transaction_id = _text(row[header["transaction_id"]], "transaction_id")
            if transaction_id in transaction_ids:
                raise PublicationError("campaign-contributions has duplicate transaction IDs")
            transaction_ids.add(transaction_id)
            correction_value = row[header["correction"]].strip().upper()
            if correction_value not in {"", "X"}:
                raise PublicationError("correction contains an unsupported value")
            donor_type = _text(row[header["donor_type"]], "donor_type").upper()
            if donor_type not in {"ENTITY", "INDIVIDUAL"}:
                raise PublicationError("donor_type contains an unsupported value")
            records.append(
                (
                    _text(recipient, "recipient"),
                    Contribution(
                        amount_cents=_amount_cents(row[header["contribution_amount"]]),
                        correction=correction_value == "X",
                        date=_date(row[header["contribution_date"]]),
                        donor=_text(row[header["donor"]], "donor"),
                        donor_type=donor_type,
                        report_url=_report_url(row[header["view_report"]]),
                        transaction_id=transaction_id,
                        type=_text(row[header["contribution_type"]], "contribution_type"),
                    ),
                )
            )
    return (
        records,
        excluded_blank_recipient_rows,
        _source_manifest(source.slug, source.dataset_id, source.title, artifact, manifest),
    )


def _source_manifest(
    slug: str, dataset_id: str, title: str, artifact: Path, manifest: dict[str, Any]
) -> dict[str, Any]:
    return {
        "slug": slug,
        "dataset_id": dataset_id,
        "title": title,
        "dataset_url": f"https://data.austintexas.gov/d/{dataset_id}",
        "artifact_sha256": artifact.stem,
        "retrieved_at": manifest["receipt"]["retrieved_at"],
    }


def _display_name(names: Counter[str]) -> str:
    return min(names, key=lambda name: (-names[name], name.casefold()))


def _slug(value: str, used: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")[:72] or "campaign"
    slug = base
    if slug in used:
        slug = f"{base}-{hashlib.sha256(value.encode()).hexdigest()[:8]}"
    used.add(slug)
    return slug


def _classification(name: str, facts: FilerFacts) -> str:
    forms = " ".join(facts.forms).casefold()
    if (
        facts.office_held
        or facts.office_sought
        or "candidate" in forms
        or "officeholder" in forms
        or "coh" in forms
    ):
        return "Candidate or officeholder"
    key = strict_name_key(name)
    if "committee" in forms or "pac" in forms or "PAC" in key.split():
        return "Political committee"
    return "Campaign recipient"


def _source_rows_url(dataset_id: str, recipients: set[str]) -> str:
    select = (
        "transaction_id,donor,donor_type,recipient,contribution_date,"
        "contribution_amount,contribution_type,correction,view_report"
    )
    literals = ["'" + value.replace("'", "''") + "'" for value in sorted(recipients)]
    where = (
        f"recipient = {literals[0]}"
        if len(literals) == 1
        else f"recipient in ({', '.join(literals)})"
    )
    query = urlencode({"$select": select, "$where": where, "$limit": "50000"}, quote_via=quote)
    return f"https://data.austintexas.gov/resource/{dataset_id}.json?{query}"


def _campaign_payload(
    *,
    key: str,
    names: Counter[str],
    records: list[Contribution],
    facts: FilerFacts,
    dataset_id: str,
    sample_limit: int,
    used_slugs: set[str],
) -> dict[str, Any]:
    name = _display_name(names)
    donors: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
    years: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    correction_rows = 0
    correction_amount_cents = 0
    amount_cents = 0
    for record in records:
        amount_cents += record.amount_cents
        donors[(record.donor, record.donor_type)][0] += 1
        donors[(record.donor, record.donor_type)][1] += record.amount_cents
        years[record.date[:4]][0] += 1
        years[record.date[:4]][1] += record.amount_cents
        if record.correction:
            correction_rows += 1
            correction_amount_cents += record.amount_cents
    top_donors = [
        {
            "name": donor,
            "donor_type": donor_type,
            "row_count": values[0],
            "amount_cents": values[1],
        }
        for (donor, donor_type), values in sorted(
            donors.items(), key=lambda item: (-item[1][1], -item[1][0], item[0][0].casefold())
        )[:20]
    ]
    by_year = [
        {"year": year, "row_count": values[0], "amount_cents": values[1]}
        for year, values in sorted(years.items(), reverse=True)
    ]
    samples = sorted(
        records,
        key=lambda record: (record.date, record.transaction_id),
        reverse=True,
    )[:sample_limit]
    return {
        "slug": _slug(key, used_slugs),
        "name": name,
        "source_names": sorted(names),
        "classification": _classification(name, facts),
        "office_held": sorted(facts.office_held),
        "office_sought": sorted(facts.office_sought),
        "amount_cents": amount_cents,
        "row_count": len(records),
        "donor_count": len({record.donor for record in records}),
        "correction_row_count": correction_rows,
        "correction_amount_cents": correction_amount_cents,
        "first_date": min(record.date for record in records),
        "last_date": max(record.date for record in records),
        "official_rows_url": _source_rows_url(dataset_id, set(names)),
        "top_donors": top_donors,
        "by_year": by_year,
        "sample_records": [
            {
                "amount_cents": record.amount_cents,
                "correction": record.correction,
                "date": record.date,
                "donor": record.donor,
                "donor_type": record.donor_type,
                "report_url": record.report_url,
                "transaction_id": record.transaction_id,
                "type": record.type,
            }
            for record in samples
        ],
    }


def build_campaign_publication(
    inventory: Inventory,
    *,
    output: Path,
    root: Path | None = None,
    sample_limit: int = DEFAULT_SAMPLE_LIMIT,
) -> Path:
    root = root or project_root()
    if sample_limit < 1 or sample_limit > 500:
        raise PublicationError("sample_limit must be between 1 and 500")
    filer_facts, reports_source = _load_filer_facts(inventory, root)
    contributions, excluded_rows, contribution_source = _load_contributions(inventory, root)

    names_by_key: dict[str, Counter[str]] = defaultdict(Counter)
    records_by_key: dict[str, list[Contribution]] = defaultdict(list)
    for recipient, record in contributions:
        key = strict_name_key(recipient)
        if not key:
            raise PublicationError("recipient has no stable typography-only key")
        names_by_key[key][recipient] += 1
        records_by_key[key].append(record)

    used_slugs: set[str] = set()
    campaigns = [
        _campaign_payload(
            key=key,
            names=names_by_key[key],
            records=records_by_key[key],
            facts=filer_facts.get(key, FilerFacts()),
            dataset_id=contribution_source["dataset_id"],
            sample_limit=sample_limit,
            used_slugs=used_slugs,
        )
        for key in sorted(records_by_key)
    ]
    kind_order = {
        "Candidate or officeholder": 0,
        "Political committee": 1,
        "Campaign recipient": 2,
    }
    campaigns.sort(
        key=lambda campaign: (
            kind_order[campaign["classification"]],
            str(campaign["name"]).casefold(),
        )
    )
    payload = {
        "schema_version": CAMPAIGN_PUBLICATION_SCHEMA_VERSION,
        "jurisdiction": "Austin, Texas",
        "sample_limit": sample_limit,
        "snapshot_date": max(record.date for _recipient, record in contributions),
        "sources": [contribution_source, reports_source],
        "raw_row_count": len(contributions) + excluded_rows,
        "published_row_count": len(contributions),
        "excluded_blank_recipient_rows": excluded_rows,
        "campaign_count": len(campaigns),
        "donor_count": len({record.donor for _recipient, record in contributions}),
        "amount_cents": sum(record.amount_cents for _recipient, record in contributions),
        "correction_row_count": sum(record.correction for _recipient, record in contributions),
        "campaigns": campaigns,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output
