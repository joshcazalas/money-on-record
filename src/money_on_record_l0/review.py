from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import cast
from urllib.parse import urlparse

from .candidates import (
    CANDIDATE_IMMUTABLE_FIELDNAMES,
    CANDIDATE_REVIEW_FIELDNAMES,
)


class ReviewError(RuntimeError):
    """A candidate review artifact is missing, invalid, or unsafe to publish."""


REVIEW_SCHEMA_VERSION = 1
REVIEW_PROVENANCES = ("HUMAN", "AI_ASSISTED")
REVIEW_FIELDNAMES = (
    "candidate_fingerprint",
    "review_status",
    "same_organization",
    "review_reason",
    "external_evidence_url",
    "review_notes",
    "reviewer",
    "reviewed_at",
)
REVIEW_DECISIONS = ("YES", "NO", "UNCERTAIN")
REVIEW_REASONS = {
    "YES": frozenset(
        {
            "INDEPENDENT_OFFICIAL_IDENTITY",
            "SHARED_OFFICIAL_IDENTIFIER",
        }
    ),
    "NO": frozenset(
        {
            "AMBIGUOUS_ABBREVIATION",
            "CONFLICTING_IDENTIFIERS",
            "DISTINCT_LEGAL_ENTITIES",
            "FRANCHISE_OR_CHAPTER",
            "PARENT_SUBSIDIARY",
            "PERSON_ORGANIZATION_COLLISION",
            "PLACEHOLDER_IDENTIFIER",
        }
    ),
    "UNCERTAIN": frozenset(
        {
            "CONFLICTING_EVIDENCE",
            "INSUFFICIENT_EVIDENCE",
            "SOURCE_DATA_AMBIGUITY",
        }
    ),
}

_CANDIDATE_ID = re.compile(r"[0-9a-f]{16}")


@dataclass(frozen=True)
class ReviewValidation:
    total: int
    reviewed: int
    unreviewed: int
    report: dict[str, object]


def initialize_review(candidates: Path, output: Path) -> Path:
    """Create a reviewer-editable copy without risking existing decisions."""
    if output.exists():
        raise ReviewError(f"refusing to overwrite existing review artifact: {output}")

    fieldnames, rows = _read_csv(candidates)
    immutable_fields = _candidate_fields(fieldnames)
    _validate_candidate_rows(rows)

    output.parent.mkdir(parents=True, exist_ok=True)
    review_fieldnames = (*immutable_fields, *REVIEW_FIELDNAMES)
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=review_fieldnames,
            lineterminator="\n",
        )
        writer.writeheader()
        for row in rows:
            immutable = {field: row[field] for field in immutable_fields}
            writer.writerow(
                {
                    **immutable,
                    "candidate_fingerprint": _fingerprint(immutable, immutable_fields),
                    "review_status": "UNREVIEWED",
                    "same_organization": "",
                    "review_reason": "",
                    "external_evidence_url": "",
                    "review_notes": "",
                    "reviewer": "",
                    "reviewed_at": "",
                }
            )
    return output


def validate_review(
    review: Path,
    *,
    candidates: Path | None = None,
    require_complete: bool = False,
) -> ReviewValidation:
    fieldnames, rows = _read_csv(review)
    expected_tail = list(REVIEW_FIELDNAMES)
    if len(fieldnames) <= len(expected_tail) or fieldnames[-len(expected_tail) :] != expected_tail:
        raise ReviewError(
            "review CSV schema is invalid; regenerate an unedited header with review-init"
        )
    immutable_fields = fieldnames[: -len(expected_tail)]
    if tuple(immutable_fields) != CANDIDATE_IMMUTABLE_FIELDNAMES:
        raise ReviewError("review CSV candidate columns do not match the current candidate schema")

    errors: list[str] = []
    seen: set[str] = set()
    complete_rows: list[dict[str, str]] = []
    for line_number, row in enumerate(rows, start=2):
        candidate_id = row["candidate_id"]
        if not _CANDIDATE_ID.fullmatch(candidate_id):
            errors.append(f"line {line_number}: candidate_id must be 16 lowercase hex characters")
        elif candidate_id in seen:
            errors.append(f"line {line_number}: duplicate candidate_id {candidate_id}")
        seen.add(candidate_id)

        immutable = {field: row[field] for field in immutable_fields}
        expected_fingerprint = _fingerprint(immutable, immutable_fields)
        if row["candidate_fingerprint"] != expected_fingerprint:
            errors.append(f"line {line_number}: immutable candidate evidence was changed")

        status = row["review_status"].strip()
        decision = row["same_organization"].strip()
        reason = row["review_reason"].strip()
        evidence = row["external_evidence_url"].strip()
        notes = row["review_notes"].strip()
        reviewer = row["reviewer"].strip()
        reviewed_at = row["reviewed_at"].strip()
        review_values = (decision, reason, evidence, notes, reviewer, reviewed_at)

        if status == "UNREVIEWED":
            if any(review_values):
                errors.append(
                    f"line {line_number}: UNREVIEWED rows must not contain partial decisions"
                )
            continue
        if status != "COMPLETE":
            errors.append(f"line {line_number}: review_status must be UNREVIEWED or COMPLETE")
            continue

        complete_rows.append(row)
        if decision not in REVIEW_DECISIONS:
            errors.append(f"line {line_number}: same_organization must be YES, NO, or UNCERTAIN")
        elif reason not in REVIEW_REASONS[decision]:
            allowed = ", ".join(sorted(REVIEW_REASONS[decision]))
            errors.append(f"line {line_number}: invalid {decision} reason; choose one of {allowed}")
        if not evidence or not _valid_evidence_urls(evidence):
            errors.append(f"line {line_number}: provide durable HTTPS evidence URLs separated by |")
        if not notes:
            errors.append(f"line {line_number}: review_notes is required")
        if not reviewer:
            errors.append(f"line {line_number}: reviewer is required")
        if not reviewed_at or not _is_aware_iso_datetime(reviewed_at):
            errors.append(
                f"line {line_number}: reviewed_at must be an ISO 8601 timestamp with timezone"
            )

    if candidates is not None:
        errors.extend(_candidate_drift_errors(candidates, immutable_fields, rows))
    if require_complete and len(complete_rows) != len(rows):
        errors.append(f"review is incomplete: {len(rows) - len(complete_rows)} row(s) remain")
    if errors:
        preview = "\n".join(f"- {error}" for error in errors[:25])
        remainder = len(errors) - 25
        suffix = f"\n- ... and {remainder} more error(s)" if remainder > 0 else ""
        raise ReviewError(
            f"review validation failed with {len(errors)} error(s):\n{preview}{suffix}"
        )

    report = _aggregate_report(rows, complete_rows)
    return ReviewValidation(
        total=len(rows),
        reviewed=len(complete_rows),
        unreviewed=len(rows) - len(complete_rows),
        report=report,
    )


def write_review_summary(
    review: Path,
    candidates: Path,
    output: Path,
    *,
    provenance: str,
) -> Path:
    if provenance not in REVIEW_PROVENANCES:
        allowed = ", ".join(REVIEW_PROVENANCES)
        raise ReviewError(f"review provenance must be one of: {allowed}")
    validation = validate_review(review, candidates=candidates, require_complete=True)
    report = {**validation.report, "review_provenance": provenance}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output


def validate_review_summary(path: Path) -> None:
    """Enforce the privacy-safe schema for a committed aggregate report."""
    try:
        raw_payload = cast(object, json.loads(path.read_text(encoding="utf-8")))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReviewError(f"{path}: expected valid UTF-8 JSON") from exc
    payload = _string_keyed_object(raw_payload, str(path))
    _require_keys(
        payload,
        {
            "review_summary_version",
            "review_provenance",
            "candidate_set_sha256",
            "complete",
            "totals",
            "decisions",
            "review_reasons",
            "evidence_tiers",
            "public_record_sources",
            "reviewed_through",
        },
        str(path),
    )
    if payload["review_summary_version"] != REVIEW_SCHEMA_VERSION:
        raise ReviewError(f"{path}: unsupported review_summary_version")
    if payload["review_provenance"] not in REVIEW_PROVENANCES:
        raise ReviewError(f"{path}: review_provenance is not recognized")
    digest = payload["candidate_set_sha256"]
    if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise ReviewError(f"{path}: candidate_set_sha256 must be lowercase SHA-256")
    if payload["complete"] is not True:
        raise ReviewError(f"{path}: only completed review summaries may be versioned")

    totals = _string_keyed_object(payload["totals"], f"{path}: totals")
    _require_keys(totals, {"candidates", "reviewed", "unreviewed"}, f"{path}: totals")
    candidate_count = _nonnegative_count(totals["candidates"], f"{path}: candidates")
    reviewed_count = _nonnegative_count(totals["reviewed"], f"{path}: reviewed")
    unreviewed_count = _nonnegative_count(totals["unreviewed"], f"{path}: unreviewed")
    if candidate_count < 1 or reviewed_count != candidate_count or unreviewed_count != 0:
        raise ReviewError(f"{path}: completed totals are internally inconsistent")

    decisions = _count_object(payload["decisions"], f"{path}: decisions")
    _require_keys(decisions, set(REVIEW_DECISIONS), f"{path}: decisions")
    if sum(decisions.values()) != reviewed_count:
        raise ReviewError(f"{path}: decision counts do not equal reviewed total")

    reasons = _count_object(payload["review_reasons"], f"{path}: review_reasons")
    known_reasons = set().union(*REVIEW_REASONS.values())
    if not reasons or not set(reasons).issubset(known_reasons):
        raise ReviewError(f"{path}: review_reasons contains an unknown or empty reason set")
    if any(count < 1 for count in reasons.values()) or sum(reasons.values()) != reviewed_count:
        raise ReviewError(f"{path}: reason counts do not equal reviewed total")

    _validate_group_report(
        payload["evidence_tiers"],
        allowed={"A_STRICT", "B_LEGAL_SUFFIX"},
        expected_total=reviewed_count,
        label=f"{path}: evidence_tiers",
    )
    _validate_group_report(
        payload["public_record_sources"],
        allowed={"contracts", "echeckbook", "purchase-orders"},
        expected_total=reviewed_count,
        label=f"{path}: public_record_sources",
    )
    reviewed_through = payload["reviewed_through"]
    if not isinstance(reviewed_through, str) or not _is_aware_iso_datetime(reviewed_through):
        raise ReviewError(f"{path}: reviewed_through must be an ISO 8601 timestamp with timezone")


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.is_file():
        raise ReviewError(f"CSV does not exist: {path}")
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ReviewError(f"CSV has no header: {path}")
        fieldnames = list(reader.fieldnames)
        if len(fieldnames) != len(set(fieldnames)):
            raise ReviewError(f"CSV has duplicate header fields: {path}")
        rows: list[dict[str, str]] = []
        for line_number, raw_row in enumerate(reader, start=2):
            if None in raw_row:
                raise ReviewError(f"line {line_number}: row has more values than the header")
            row: dict[str, str] = {}
            for field in fieldnames:
                value = raw_row.get(field)
                if value is None:
                    raise ReviewError(f"line {line_number}: row is missing field {field}")
                row[field] = value
            rows.append(row)
    if not rows:
        raise ReviewError(f"CSV has no candidate rows: {path}")
    return fieldnames, rows


def _candidate_fields(fieldnames: list[str]) -> tuple[str, ...]:
    immutable = tuple(field for field in fieldnames if field not in CANDIDATE_REVIEW_FIELDNAMES)
    if immutable != CANDIDATE_IMMUTABLE_FIELDNAMES:
        raise ReviewError("candidate CSV columns do not match the current candidate schema")
    unexpected = set(fieldnames) - set(CANDIDATE_IMMUTABLE_FIELDNAMES + CANDIDATE_REVIEW_FIELDNAMES)
    if unexpected:
        raise ReviewError(f"candidate CSV has unexpected columns: {', '.join(sorted(unexpected))}")
    return immutable


def _validate_candidate_rows(rows: list[dict[str, str]]) -> None:
    seen: set[str] = set()
    for line_number, row in enumerate(rows, start=2):
        candidate_id = row["candidate_id"]
        if not _CANDIDATE_ID.fullmatch(candidate_id):
            raise ReviewError(
                f"line {line_number}: candidate_id must be 16 lowercase hex characters"
            )
        if candidate_id in seen:
            raise ReviewError(f"line {line_number}: duplicate candidate_id {candidate_id}")
        seen.add(candidate_id)


def _fingerprint(row: dict[str, str], fieldnames: tuple[str, ...] | list[str]) -> str:
    payload = {field: row[field] for field in fieldnames}
    canonical = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _candidate_drift_errors(
    candidates: Path,
    immutable_fields: list[str],
    review_rows: list[dict[str, str]],
) -> list[str]:
    candidate_header, candidate_rows = _read_csv(candidates)
    candidate_fields = _candidate_fields(candidate_header)
    _validate_candidate_rows(candidate_rows)
    if tuple(immutable_fields) != candidate_fields:
        return ["candidate and review schemas differ"]

    expected = {row["candidate_id"]: _fingerprint(row, candidate_fields) for row in candidate_rows}
    actual = {row["candidate_id"]: row["candidate_fingerprint"] for row in review_rows}
    errors: list[str] = []
    missing = sorted(expected.keys() - actual.keys())
    added = sorted(actual.keys() - expected.keys())
    changed = sorted(
        candidate_id
        for candidate_id in expected.keys() & actual.keys()
        if expected[candidate_id] != actual[candidate_id]
    )
    if missing:
        errors.append(f"review is missing {len(missing)} current candidate(s)")
    if added:
        errors.append(f"review contains {len(added)} candidate(s) no longer generated")
    if changed:
        errors.append(f"candidate evidence drifted for {len(changed)} reviewed row(s)")
    return errors


def _valid_evidence_urls(value: str) -> bool:
    urls = [item.strip() for item in value.split("|")]
    if not urls or any(not url for url in urls):
        return False
    for url in urls:
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
            return False
    return True


def _is_aware_iso_datetime(value: str) -> bool:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def _string_keyed_object(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ReviewError(f"{label}: expected an object with string keys")
    return cast(dict[str, object], value)


def _require_keys(value: Mapping[str, object], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise ReviewError(f"{label}: fields do not match the versioned review-summary schema")


def _nonnegative_count(value: object, label: str) -> int:
    if type(value) is not int or value < 0:
        raise ReviewError(f"{label}: expected a non-negative integer")
    return value


def _count_object(value: object, label: str) -> dict[str, int]:
    payload = _string_keyed_object(value, label)
    return {key: _nonnegative_count(count, f"{label}.{key}") for key, count in payload.items()}


def _validate_group_report(
    value: object,
    *,
    allowed: set[str],
    expected_total: int,
    label: str,
) -> None:
    groups = _string_keyed_object(value, label)
    if not groups or not set(groups).issubset(allowed):
        raise ReviewError(f"{label}: contains an unknown or empty group set")
    combined_total = 0
    for group, raw_group in groups.items():
        group_label = f"{label}.{group}"
        payload = _string_keyed_object(raw_group, group_label)
        _require_keys(payload, {"total", "reviewed", "decisions"}, group_label)
        total = _nonnegative_count(payload["total"], f"{group_label}.total")
        reviewed = _nonnegative_count(payload["reviewed"], f"{group_label}.reviewed")
        decisions = _count_object(payload["decisions"], f"{group_label}.decisions")
        _require_keys(decisions, set(REVIEW_DECISIONS), f"{group_label}.decisions")
        if total < 1 or reviewed != total or sum(decisions.values()) != total:
            raise ReviewError(f"{group_label}: counts are internally inconsistent")
        combined_total += total
    if combined_total != expected_total:
        raise ReviewError(f"{label}: group totals do not equal reviewed total")


def _aggregate_report(
    rows: list[dict[str, str]],
    complete_rows: list[dict[str, str]],
) -> dict[str, object]:
    decisions = Counter(row["same_organization"].strip() for row in complete_rows)
    reasons = Counter(row["review_reason"].strip() for row in complete_rows)
    reviewed_ids = {row["candidate_id"] for row in complete_rows}
    tier_totals = Counter(row["evidence_tier"] for row in rows)
    source_totals = Counter(row["public_record_source"] for row in rows)
    tier_reviewed = Counter(row["evidence_tier"] for row in complete_rows)
    source_reviewed = Counter(row["public_record_source"] for row in complete_rows)
    tier_decisions: dict[str, Counter[str]] = defaultdict(Counter)
    source_decisions: dict[str, Counter[str]] = defaultdict(Counter)
    for row in complete_rows:
        tier_decisions[row["evidence_tier"]][row["same_organization"]] += 1
        source_decisions[row["public_record_source"]][row["same_organization"]] += 1

    candidate_set = "\n".join(
        f"{row['candidate_id']}:{row['candidate_fingerprint']}"
        for row in sorted(rows, key=lambda item: item["candidate_id"])
    )
    reviewed_times = sorted(row["reviewed_at"] for row in complete_rows)
    return {
        "review_summary_version": REVIEW_SCHEMA_VERSION,
        "candidate_set_sha256": hashlib.sha256(candidate_set.encode("utf-8")).hexdigest(),
        "complete": len(reviewed_ids) == len(rows),
        "totals": {
            "candidates": len(rows),
            "reviewed": len(reviewed_ids),
            "unreviewed": len(rows) - len(reviewed_ids),
        },
        "decisions": {decision: decisions[decision] for decision in REVIEW_DECISIONS},
        "review_reasons": dict(sorted(reasons.items())),
        "evidence_tiers": _group_report(tier_totals, tier_reviewed, tier_decisions),
        "public_record_sources": _group_report(source_totals, source_reviewed, source_decisions),
        "reviewed_through": reviewed_times[-1] if reviewed_times else None,
    }


def _group_report(
    totals: Counter[str],
    reviewed: Counter[str],
    decisions: dict[str, Counter[str]],
) -> dict[str, object]:
    return {
        group: {
            "total": totals[group],
            "reviewed": reviewed[group],
            "decisions": {decision: decisions[group][decision] for decision in REVIEW_DECISIONS},
        }
        for group in sorted(totals)
    }
