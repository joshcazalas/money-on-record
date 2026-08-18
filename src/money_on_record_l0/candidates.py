from __future__ import annotations

import csv
import hashlib
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import quote, urlencode

from .acquire import latest_artifact, project_root
from .contracts import Inventory, SourceContract
from .normalize import has_invalid_code_prefix, strict_name_key, suffix_candidate_key
from .source_schema import resolved_source_header


class CandidateError(RuntimeError):
    """The conservative candidate experiment cannot be run safely."""


CANDIDATE_IMMUTABLE_FIELDNAMES = (
    "candidate_id",
    "evidence_tier",
    "campaign_name",
    "campaign_names_aggregated",
    "public_record_name",
    "public_record_names_aggregated",
    "public_record_source",
    "public_record_code",
    "strict_campaign_key",
    "strict_public_key",
    "suffix_candidate_key",
    "campaign_rows",
    "public_record_rows",
    "campaign_amount_field",
    "campaign_amount",
    "public_record_amount_field",
    "public_record_amount",
    "campaign_artifact_sha256",
    "public_record_artifact_sha256",
    "campaign_source_rows_url",
    "public_record_source_rows_url",
    "campaign_keys_for_suffix",
    "public_keys_for_suffix",
)
CANDIDATE_REVIEW_FIELDNAMES = (
    "review_status",
    "same_organization",
    "external_evidence_url",
    "review_notes",
)
CANDIDATE_FIELDNAMES = CANDIDATE_IMMUTABLE_FIELDNAMES + CANDIDATE_REVIEW_FIELDNAMES


@dataclass
class EntityAggregate:
    names: Counter[str] = field(default_factory=Counter)
    row_count: int = 0
    amount: Decimal = Decimal(0)

    @property
    def display_name(self) -> str:
        return min(self.names, key=lambda name: (-self.names[name], name.casefold()))


@dataclass
class PublicAggregate(EntityAggregate):
    source_slug: str = ""
    code: str = ""
    amount_field: str | None = None


def _decimal(value: str) -> Decimal:
    try:
        return Decimal(value.replace("$", "").replace(",", "").strip() or "0")
    except InvalidOperation:
        return Decimal(0)


def _require_fields(
    header: dict[str, str],
    names: list[str | None],
    source: SourceContract,
) -> None:
    required = {name for name in names if name}
    missing = sorted(required - header.keys())
    if missing:
        raise CandidateError(f"{source.slug}: required fields missing: {', '.join(missing)}")


def _load_campaign_entities(
    source: SourceContract,
    root: Path,
) -> dict[str, EntityAggregate]:
    if not source.organization_name_field or not source.organization_type_field:
        raise CandidateError("campaign contribution contract lacks organization type controls")
    artifact = latest_artifact(source, "acquire-csv", root)
    aggregates: dict[str, EntityAggregate] = defaultdict(EntityAggregate)
    amount_field = source.candidate_amount_field
    allowed_types = {value.casefold() for value in source.organization_type_values}

    with artifact.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise CandidateError(f"{source.slug}: missing CSV header")
        header = resolved_source_header(reader.fieldnames, source, root)
        _require_fields(
            header,
            [source.organization_name_field, source.organization_type_field, amount_field],
            source,
        )
        for row in reader:
            type_value = row[header[source.organization_type_field]].strip().casefold()
            if type_value not in allowed_types:
                continue
            name = row[header[source.organization_name_field]].strip()
            key = strict_name_key(name)
            if not key:
                continue
            aggregate = aggregates[key]
            aggregate.names[name] += 1
            aggregate.row_count += 1
            if amount_field:
                aggregate.amount += _decimal(row[header[amount_field]])

    if not aggregates:
        configured = ", ".join(source.organization_type_values)
        raise CandidateError(
            f"{source.slug}: no organization rows matched configured types ({configured}); "
            "inspect the frozen field dictionary before changing this safety gate"
        )
    return dict(aggregates)


def _load_public_entities(
    source: SourceContract,
    root: Path,
) -> dict[tuple[str, str], PublicAggregate]:
    if not source.organization_name_field:
        raise CandidateError(f"{source.slug}: no organization_name_field configured")
    artifact = latest_artifact(source, "acquire-csv", root)
    aggregates: dict[tuple[str, str], PublicAggregate] = {}
    amount_field = source.candidate_amount_field

    with artifact.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise CandidateError(f"{source.slug}: missing CSV header")
        header = resolved_source_header(reader.fieldnames, source, root)
        _require_fields(
            header,
            [
                source.organization_name_field,
                source.organization_code_field,
                amount_field,
            ],
            source,
        )
        for row in reader:
            name = row[header[source.organization_name_field]].strip()
            code = (
                row[header[source.organization_code_field]].strip()
                if source.organization_code_field
                else ""
            )
            if not name or has_invalid_code_prefix(code, source.invalid_code_prefixes):
                continue
            strict_key = strict_name_key(name)
            if not strict_key:
                continue
            aggregate_key = (strict_key, code)
            aggregate = aggregates.setdefault(
                aggregate_key,
                PublicAggregate(
                    source_slug=source.slug,
                    code=code,
                    amount_field=amount_field,
                ),
            )
            aggregate.names[name] += 1
            aggregate.row_count += 1
            if amount_field and amount_field in header:
                aggregate.amount += _decimal(row[header[amount_field]])
    return aggregates


def generate_candidates(
    inventory: Inventory,
    *,
    limit: int = 50,
    root: Path | None = None,
) -> Path:
    root = root or project_root()
    campaign_source = inventory.require("campaign-contributions")
    campaign_artifact = latest_artifact(campaign_source, "acquire-csv", root)
    campaign = _load_campaign_entities(campaign_source, root)
    public: list[tuple[tuple[str, str], PublicAggregate]] = []
    for slug in ("echeckbook", "contracts", "purchase-orders"):
        public.extend(_load_public_entities(inventory.require(slug), root).items())

    campaign_suffix: dict[str, set[str]] = defaultdict(set)
    for strict_key in campaign:
        candidate_key = suffix_candidate_key(strict_key)
        if candidate_key:
            campaign_suffix[candidate_key].add(strict_key)
    public_suffix: dict[str, set[str]] = defaultdict(set)
    for (strict_key, _code), _aggregate in public:
        candidate_key = suffix_candidate_key(strict_key)
        if candidate_key:
            public_suffix[candidate_key].add(strict_key)

    rows: list[dict[str, str | int]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for (public_strict, _code), public_aggregate in public:
        suffix_key = suffix_candidate_key(public_strict)
        possible_campaign_keys: set[str] = set()
        if public_strict in campaign:
            possible_campaign_keys.add(public_strict)
        possible_campaign_keys.update(campaign_suffix.get(suffix_key, set()))

        for campaign_strict in possible_campaign_keys:
            campaign_aggregate = campaign[campaign_strict]
            tier = "A_STRICT" if campaign_strict == public_strict else "B_LEGAL_SUFFIX"
            identity = (
                campaign_strict,
                public_strict,
                public_aggregate.source_slug,
                public_aggregate.code,
            )
            if identity in seen:
                continue
            seen.add(identity)
            candidate_id = hashlib.sha256("|".join(identity).encode()).hexdigest()[:16]
            public_source = inventory.require(public_aggregate.source_slug)
            public_artifact = latest_artifact(public_source, "acquire-csv", root)
            rows.append(
                {
                    "candidate_id": candidate_id,
                    "evidence_tier": tier,
                    "campaign_name": campaign_aggregate.display_name,
                    "campaign_names_aggregated": " | ".join(sorted(campaign_aggregate.names)),
                    "public_record_name": public_aggregate.display_name,
                    "public_record_names_aggregated": " | ".join(sorted(public_aggregate.names)),
                    "public_record_source": public_aggregate.source_slug,
                    "public_record_code": public_aggregate.code,
                    "strict_campaign_key": campaign_strict,
                    "strict_public_key": public_strict,
                    "suffix_candidate_key": suffix_key,
                    "campaign_rows": campaign_aggregate.row_count,
                    "public_record_rows": public_aggregate.row_count,
                    "campaign_amount_field": campaign_source.candidate_amount_field or "",
                    "campaign_amount": str(campaign_aggregate.amount),
                    "public_record_amount_field": public_aggregate.amount_field or "",
                    "public_record_amount": (
                        str(public_aggregate.amount) if public_aggregate.amount_field else ""
                    ),
                    "campaign_artifact_sha256": campaign_artifact.stem,
                    "public_record_artifact_sha256": public_artifact.stem,
                    "campaign_source_rows_url": _source_rows_url(
                        campaign_source,
                        {
                            campaign_source.organization_name_field: campaign_aggregate.names,
                            campaign_source.organization_type_field: (
                                campaign_source.organization_type_values
                            ),
                        },
                    ),
                    "public_record_source_rows_url": _source_rows_url(
                        public_source,
                        {
                            public_source.organization_name_field: public_aggregate.names,
                            public_source.organization_code_field: [public_aggregate.code],
                        },
                    ),
                    "campaign_keys_for_suffix": len(campaign_suffix.get(suffix_key, set())),
                    "public_keys_for_suffix": len(public_suffix.get(suffix_key, set())),
                    "review_status": "UNREVIEWED",
                    "same_organization": "",
                    "external_evidence_url": "",
                    "review_notes": "",
                }
            )

    rows.sort(
        key=lambda row: (
            0 if row["evidence_tier"] == "A_STRICT" else 1,
            -int(row["campaign_rows"]),
            -int(row["public_record_rows"]),
            str(row["campaign_name"]).casefold(),
            str(row["public_record_name"]).casefold(),
        )
    )
    selected = _stratified_limit(rows, limit)
    output_dir = root / "data" / "derived"
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / "l0-organization-candidates.csv"
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=CANDIDATE_FIELDNAMES,
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(selected)
    return output


def _source_rows_url(
    source: SourceContract,
    field_values: dict[str | None, Iterable[str]],
) -> str:
    clauses: list[str] = []
    for field_name, raw_values in field_values.items():
        if not field_name:
            continue
        values = sorted({str(value) for value in raw_values})
        literals = [_soql_literal(value) for value in values]
        if len(literals) == 1:
            clauses.append(f"{field_name} = {literals[0]}")
        elif literals:
            clauses.append(f"{field_name} in ({', '.join(literals)})")
    query = urlencode(
        {"$where": " AND ".join(clauses), "$limit": "50000"},
        quote_via=quote,
    )
    return f"https://data.austintexas.gov/resource/{source.dataset_id}.json?{query}"


def _soql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _stratified_limit(rows: list[dict[str, str | int]], limit: int) -> list[dict[str, str | int]]:
    if limit < 1:
        raise ValueError("limit must be positive")
    strict = [row for row in rows if row["evidence_tier"] == "A_STRICT"]
    suffix = [row for row in rows if row["evidence_tier"] == "B_LEGAL_SUFFIX"]
    first_share = (limit + 1) // 2
    selected = strict[:first_share] + suffix[: limit - first_share]
    selected_ids = {str(row["candidate_id"]) for row in selected}
    if len(selected) < limit:
        selected.extend(row for row in rows if str(row["candidate_id"]) not in selected_ids)
    return selected[:limit]
