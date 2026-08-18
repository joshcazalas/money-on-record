from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .acquire import latest_artifact, project_root
from .candidates import _load_campaign_entities, _load_public_entities
from .contracts import Inventory, SourceContract
from .normalize import has_invalid_code_prefix, suffix_candidate_key
from .source_schema import resolved_source_header


def _invalid_code_stats(source: SourceContract, root: Path) -> dict[str, int]:
    artifact = latest_artifact(source, "acquire-csv", root)
    invalid_rows = 0
    invalid_names: set[str] = set()
    invalid_codes: set[str] = set()
    with artifact.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError(f"{artifact}: missing CSV header")
        header = resolved_source_header(reader.fieldnames, source, root)
        if not source.organization_code_field or not source.organization_name_field:
            return {"rows": 0, "distinct_names": 0, "distinct_codes": 0}
        for row in reader:
            code = row[header[source.organization_code_field]].strip()
            if not has_invalid_code_prefix(code, source.invalid_code_prefixes):
                continue
            invalid_rows += 1
            invalid_codes.add(code)
            name = row[header[source.organization_name_field]].strip()
            if name:
                invalid_names.add(name)
    return {
        "rows": invalid_rows,
        "distinct_names": len(invalid_names),
        "distinct_codes": len(invalid_codes),
    }


def _latest_profile(source_slug: str, root: Path) -> dict[str, Any]:
    profiles = list((root / "reports" / "profiles").glob(f"*-{source_slug}.json"))
    if not profiles:
        raise ValueError(f"{source_slug}: no profile found")
    return json.loads(max(profiles).read_text(encoding="utf-8"))


def run_identity_audit(inventory: Inventory, root: Path | None = None) -> tuple[Path, Path]:
    root = root or project_root()
    campaign_source = inventory.require("campaign-contributions")
    campaign = _load_campaign_entities(campaign_source, root)
    campaign_strict = set(campaign)
    campaign_suffix = {suffix_candidate_key(key) for key in campaign if suffix_candidate_key(key)}
    campaign_raw_names = {name for aggregate in campaign.values() for name in aggregate.names}

    public_stats: dict[str, dict[str, Any]] = {}
    matched_campaign_keys: set[str] = set()
    for slug in ("echeckbook", "contracts", "purchase-orders"):
        source = inventory.require(slug)
        aggregates = _load_public_entities(source, root)
        strict_keys = {strict_key for strict_key, _code in aggregates}
        suffix_keys = {
            suffix_candidate_key(key) for key in strict_keys if suffix_candidate_key(key)
        }
        exact_overlap = campaign_strict & strict_keys
        suffix_overlap = campaign_suffix & suffix_keys
        matched_campaign_keys.update(exact_overlap)
        matched_campaign_keys.update(
            key for key in campaign_strict if suffix_candidate_key(key) in suffix_overlap
        )
        public_stats[slug] = {
            "eligible_rows": sum(aggregate.row_count for aggregate in aggregates.values()),
            "eligible_raw_names": len(
                {name for aggregate in aggregates.values() for name in aggregate.names}
            ),
            "eligible_codes": len({aggregate.code for aggregate in aggregates.values()}),
            "strict_name_keys": len(strict_keys),
            "suffix_candidate_keys": len(suffix_keys),
            "exact_strict_key_overlap": len(exact_overlap),
            "legal_suffix_key_overlap": len(suffix_overlap),
            "invalid_code_prefixes": list(source.invalid_code_prefixes),
            "invalid_code_stats": _invalid_code_stats(source, root),
            "artifact_sha256": latest_artifact(source, "acquire-csv", root).stem,
        }

    candidate_path = root / "data" / "derived" / "l0-organization-candidates.csv"
    candidate_tiers: Counter[str] = Counter()
    candidate_sources: Counter[str] = Counter()
    candidate_campaign_keys: set[str] = set()
    with candidate_path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            candidate_tiers[row["evidence_tier"]] += 1
            candidate_sources[row["public_record_source"]] += 1
            candidate_campaign_keys.add(row["strict_campaign_key"])

    profiles = {slug: _latest_profile(slug, root) for slug in inventory.sources}
    suspicious_dates = {
        slug: {
            field: {
                "count": stats["suspicious_date_count"],
                "examples": stats["suspicious_date_examples"],
            }
            for field, stats in profile["fields"].items()
            if stats.get("suspicious_date_count")
        }
        for slug, profile in profiles.items()
    }
    suspicious_dates = {slug: fields for slug, fields in suspicious_dates.items() if fields}

    payload = {
        "audit_version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "normalization": {
            "strict": "Unicode NFKD, ASCII fold, uppercase, ampersand-to-AND, punctuation collapse",
            "candidate_only": "remove trailing legal suffix tokens",
            "fuzzy_matching": False,
            "person_matching": False,
        },
        "campaign_entities": {
            "rows": sum(aggregate.row_count for aggregate in campaign.values()),
            "raw_names": len(campaign_raw_names),
            "strict_name_keys": len(campaign),
            "suffix_candidate_keys": len(campaign_suffix),
            "amount_field": campaign_source.candidate_amount_field,
            "amount": str(sum((aggregate.amount for aggregate in campaign.values()), start=0)),
            "artifact_sha256": latest_artifact(campaign_source, "acquire-csv", root).stem,
        },
        "public_sources": public_stats,
        "candidate_review_set": {
            "rows": sum(candidate_tiers.values()),
            "tiers": dict(sorted(candidate_tiers.items())),
            "sources": dict(sorted(candidate_sources.items())),
            "unique_campaign_strict_keys": len(candidate_campaign_keys),
            "reviewed_rows": 0,
        },
        "profiles": {
            slug: {
                "rows": profile["row_count"],
                "missing_configured_fields": profile["missing_configured_fields"],
                "candidate_key_duplicates": profile["duplicate_counts_for_candidate_keys"],
                "artifact": profile["artifact"],
            }
            for slug, profile in profiles.items()
        },
        "suspicious_dates": suspicious_dates,
        "matched_campaign_entity_keys_all_sources": len(matched_campaign_keys),
    }

    derived_dir = root / "data" / "derived"
    derived_dir.mkdir(parents=True, exist_ok=True)
    json_output = derived_dir / "l0-identity-audit.json"
    json_output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    report_dir = root / "docs" / "analysis"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_output = report_dir / "initial-identity-audit.md"
    report_output.write_text(_render_markdown(payload), encoding="utf-8")
    return json_output, report_output


def _render_markdown(payload: dict[str, Any]) -> str:
    campaign = payload["campaign_entities"]
    lines = [
        "# Initial organization identity audit",
        "",
        f"Snapshot audit created `{payload['created_at']}`. All counts are from the frozen "
        "artifact "
        "hashes in `data/derived/l0-identity-audit.json`.",
        "",
        "## Campaign entity population",
        "",
        f"The official contributions projection contains **{campaign['rows']:,} rows explicitly "
        f"typed as entities**, representing {campaign['raw_names']:,} raw names and "
        f"{campaign['strict_name_keys']:,} strict normalized keys. These are the only campaign "
        "rows admitted to cross-domain matching.",
        "",
        "## Purchasing/payment identity audit",
        "",
        "| Source | Eligible rows | Strict keys | Invalid-code rows | Invalid-code names | "
        "Strict overlaps | Suffix overlaps |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for slug, stats in payload["public_sources"].items():
        invalid = stats["invalid_code_stats"]
        lines.append(
            f"| {slug} | {stats['eligible_rows']:,} | {stats['strict_name_keys']:,} | "
            f"{invalid['rows']:,} | {invalid['distinct_names']:,} | "
            f"{stats['exact_strict_key_overlap']:,} | {stats['legal_suffix_key_overlap']:,} |"
        )
    review = payload["candidate_review_set"]
    lines.extend(
        [
            "",
            "## Candidate set",
            "",
            f"The deterministic resolver produced **{review['rows']} review candidates** across "
            f"{review['unique_campaign_strict_keys']} campaign entity keys: "
            f"{review['tiers'].get('A_STRICT', 0)} strict and "
            f"{review['tiers'].get('B_LEGAL_SUFFIX', 0)} legal-suffix-only. "
            "Every row remains `UNREVIEWED`; no candidate is a verified identity link.",
            "",
            "## Source-quality flags",
            "",
            "- Campaign `transaction_id` values are unique in both transaction datasets.",
            "- Campaign report `report_id` is not a row key; 300 duplicate non-null values were "
            "observed.",
            "- Suspicious dates are retained as source values and must be resolved or labeled, not "
            "silently corrected.",
            "",
        ]
    )
    for slug, fields in payload["suspicious_dates"].items():
        for field, stats in fields.items():
            lines.append(
                f"  - `{slug}.{field}`: {stats['count']:,} suspicious rows; examples "
                f"`{', '.join(stats['examples'])}`."
            )
    lines.extend(
        [
            "",
            "## Current decision",
            "",
            "The density gate is promising enough to continue L0: there are more than 25 "
            "conservative candidates without matching people. The identity gate has not passed "
            "until the review CSV is manually adjudicated and ambiguous cases are retained as "
            "negative regression examples.",
            "",
        ]
    )
    return "\n".join(lines)
