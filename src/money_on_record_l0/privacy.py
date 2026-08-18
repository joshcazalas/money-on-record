from __future__ import annotations

import csv
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from .contracts import SourceContract
from .fields import canonical_header

_PII_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("email", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)),
    (
        "phone",
        re.compile(r"(?<!\d)(?:\+?1[ .-]?)?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}(?!\d)"),
    ),
    ("ssn", re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")),
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


class PublicSchemaError(ValueError):
    """A proposed public artifact contains a field outside its source allowlist."""


@dataclass(frozen=True)
class PrivacyFinding:
    row_number: int
    field: str
    kind: str
    preview: str


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
    findings: list[PrivacyFinding] = []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise PublicSchemaError(f"{path}: missing CSV header")
        header = validate_public_header(reader.fieldnames, source)
        for row_number, row in enumerate(reader, start=2):
            for canonical, source_name in header.items():
                value = row.get(source_name, "")
                if not value:
                    continue
                for kind, pattern in _PII_PATTERNS:
                    match = pattern.search(value)
                    if match:
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


def _safe_preview(value: str) -> str:
    """Return enough context to debug a failure without repeating the PII."""
    if len(value) <= 4:
        return "[redacted]"
    return f"{value[:2]}…{value[-2:]}"
