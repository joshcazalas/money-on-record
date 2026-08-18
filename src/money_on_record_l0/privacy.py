from __future__ import annotations

import csv
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from .contracts import SourceContract
from .fields import canonical_header
from .source_schema import resolved_source_header

_PII_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("email", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)),
    (
        "phone",
        re.compile(
            r"(?<!\d)(?:\+?1[\s./-]*)?(?:\(\s*\d{3}\s*\)|\d{3})"
            r"[\s./-]*\d{3}[\s./-]*\d{4}(?!\d)"
        ),
    ),
    ("ssn", re.compile(r"(?<!\d)\d{3}[ -]\d{2}[ -]\d{4}(?!\d)")),
    (
        "street_address",
        re.compile(
            r"\bP(?:OST(?:AL)?)?\.?\s*O(?:FFICE)?\.?\s+BOX\s+\d+[A-Z0-9-]*\b",
            re.IGNORECASE,
        ),
    ),
    (
        "street_address",
        re.compile(
            r"\b\d{1,6}\s+(?:[A-Z0-9.'-]+\s+){0,5}"
            r"(?:ST(?:REET)?|AVE(?:NUE)?|RD|ROAD|BLVD|BOULEVARD|DR|DRIVE|LN|LANE|"
            r"CT|COURT|WAY|PL|PLACE|PKWY|PARKWAY)\b",
            re.IGNORECASE,
        ),
    ),
)

_STRUCTURED_IDENTIFIER_PARTS = frozenset({"cd", "code", "id", "key", "no", "number"})


class PublicSchemaError(ValueError):
    """A proposed public artifact contains a field outside its source allowlist."""


@dataclass(frozen=True)
class PrivacyFinding:
    row_number: int
    field: str
    kind: str
    preview: str


def contains_pii(value: str, *, field: str = "") -> bool:
    """Return whether a value has a direct-contact or address-shaped match."""
    return any(True for _kind, _match in _matches(value, field))


def validate_public_header(
    fieldnames: Iterable[str | None], source: SourceContract
) -> dict[str, str]:
    header = canonical_header(fieldnames)
    unexpected = sorted(set(header) - set(source.public_fields))
    forbidden = sorted(
        field
        for field in header
        if field in source.restricted_fields
        or any(
            pattern.casefold() in field.casefold() for pattern in source.restricted_field_patterns
        )
    )
    messages = []
    if unexpected:
        messages.append(f"not allowlisted: {', '.join(unexpected)}")
    if forbidden:
        messages.append(f"matches restricted pattern: {', '.join(forbidden)}")
    if messages:
        raise PublicSchemaError(f"{source.slug} public schema rejected ({'; '.join(messages)})")
    return header


def scan_public_csv(
    path: Path,
    source: SourceContract,
    *,
    maximum_findings: int = 25,
) -> list[PrivacyFinding]:
    _require_positive_limit(maximum_findings)
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise PublicSchemaError(f"{path}: missing CSV header")
        header = validate_public_header(reader.fieldnames, source)
        return _scan_reader(reader, header, path, maximum_findings)


def scan_source_csv(
    path: Path,
    source: SourceContract,
    *,
    root: Path | None = None,
    maximum_findings: int = 25,
) -> list[PrivacyFinding]:
    """Scan allowlisted values in a full, private source artifact without exporting them."""
    _require_positive_limit(maximum_findings)
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise PublicSchemaError(f"{path}: missing CSV header")
        resolved = resolved_source_header(reader.fieldnames, source, root)
        missing = sorted(set(source.public_fields) - set(resolved))
        if missing:
            raise PublicSchemaError(
                f"{source.slug} source schema is missing allowlisted fields: {', '.join(missing)}"
            )
        selected = {field: resolved[field] for field in source.public_fields}
        return _scan_reader(reader, selected, path, maximum_findings)


def _scan_reader(
    reader: csv.DictReader[str],
    header: dict[str, str],
    path: Path,
    maximum_findings: int,
) -> list[PrivacyFinding]:
    findings: list[PrivacyFinding] = []
    for row_number, row in enumerate(reader, start=2):
        if None in row:
            raise PublicSchemaError(
                f"{path}: row {row_number} has values beyond the declared CSV header"
            )
        for canonical, source_name in header.items():
            value = row.get(source_name, "")
            if not value:
                continue
            for kind, match in _matches(value, canonical):
                findings.append(
                    PrivacyFinding(
                        row_number=row_number,
                        field=canonical,
                        kind=kind,
                        preview=_safe_preview(match.group()),
                    )
                )
                if len(findings) >= maximum_findings:
                    return findings
    return findings


def _matches(value: str, field: str) -> Iterable[tuple[str, re.Match[str]]]:
    for kind, pattern in _PII_PATTERNS:
        if kind in {"phone", "ssn"} and _is_structured_identifier(field):
            continue
        match = pattern.search(value)
        if match:
            yield kind, match


def _is_structured_identifier(field: str) -> bool:
    """Avoid treating digit-only opaque identifiers as phone or SSN values."""
    return bool(_STRUCTURED_IDENTIFIER_PARTS.intersection(field.split("_")))


def _require_positive_limit(maximum_findings: int) -> None:
    if maximum_findings < 1:
        raise ValueError("maximum_findings must be positive")


def _safe_preview(value: str) -> str:
    """Keep scanner output and CI logs from repeating any part of a matched value."""
    del value
    return "[redacted]"
