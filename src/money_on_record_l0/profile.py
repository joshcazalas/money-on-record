from __future__ import annotations

import csv
import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .acquire import latest_artifact, project_root, timestamp_for_path
from .contracts import SourceContract
from .source_schema import resolved_source_header

_SUSPICIOUS_MAX_YEAR = datetime.now(UTC).year + 20


@dataclass
class TrackedField:
    nulls: int = 0
    minimum: str | None = None
    maximum: str | None = None
    distinct: set[str] | None = None
    frequencies: Counter[str] | None = None
    invalid_date_count: int = 0
    suspicious_date_count: int = 0
    suspicious_date_examples: set[str] | None = None
    _minimum_date: datetime | None = None
    _maximum_date: datetime | None = None

    def observe(
        self,
        value: str,
        *,
        collect_distinct: bool,
        collect_frequencies: bool,
        collect_range: bool,
    ) -> None:
        value = value.strip()
        if not value:
            self.nulls += 1
            return
        if collect_range:
            parsed = _parse_date(value)
            if parsed is None:
                self.invalid_date_count += 1
            elif self._minimum_date is None or parsed < self._minimum_date:
                self.minimum = value
                self._minimum_date = parsed
            if parsed is not None and (self._maximum_date is None or parsed > self._maximum_date):
                self.maximum = value
                self._maximum_date = parsed
            if parsed is not None and (parsed.year < 1900 or parsed.year > _SUSPICIOUS_MAX_YEAR):
                self.suspicious_date_count += 1
                if self.suspicious_date_examples is None:
                    self.suspicious_date_examples = set()
                if len(self.suspicious_date_examples) < 5:
                    self.suspicious_date_examples.add(value)
        if collect_distinct:
            if self.distinct is None:
                self.distinct = set()
            self.distinct.add(value)
        if collect_frequencies:
            if self.frequencies is None:
                self.frequencies = Counter()
            self.frequencies[value] += 1


def _parse_date(value: str) -> datetime | None:
    for date_format in ("%m/%d/%Y", "%m/%d/%Y %I:%M:%S %p", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, date_format).replace(tzinfo=UTC)
        except ValueError:
            pass
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=parsed.tzinfo or UTC).astimezone(UTC)
    except ValueError:
        return None


def profile_csv(source: SourceContract, root: Path | None = None) -> Path:
    root = root or project_root()
    artifact = latest_artifact(source, "acquire-csv", root)
    distinct_names = set(
        source.identity_fields
        + source.categorical_fields
        + source.date_fields
        + source.amount_fields
        + source.uniqueness_fields
    )
    configured_names = distinct_names | set(source.public_fields)
    fields: dict[str, TrackedField] = {}
    row_count = 0

    with artifact.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError(f"{artifact}: missing CSV header")
        header = resolved_source_header(reader.fieldnames, source, root)
        fields = {canonical: TrackedField() for canonical in header}
        missing_configured_fields = sorted(configured_names - header.keys())

        for row in reader:
            row_count += 1
            for canonical, source_name in header.items():
                fields[canonical].observe(
                    row.get(source_name, ""),
                    collect_distinct=canonical in distinct_names,
                    collect_frequencies=canonical in source.categorical_fields,
                    collect_range=canonical in source.date_fields,
                )

    duplicate_counts: dict[str, int | None] = {}
    for name in source.uniqueness_fields:
        stats = fields.get(name, TrackedField())
        duplicate_counts[name] = (
            None if stats.distinct is None else row_count - stats.nulls - len(stats.distinct)
        )

    observed_fields: dict[str, dict[str, Any]] = {}
    for name, stats in fields.items():
        observed_fields[name] = {
            "nulls": stats.nulls,
            "null_rate": (stats.nulls / row_count) if row_count else None,
            "minimum": stats.minimum if name in source.date_fields else None,
            "maximum": stats.maximum if name in source.date_fields else None,
            "distinct": len(stats.distinct) if stats.distinct is not None else None,
            "top_values": stats.frequencies.most_common(25) if stats.frequencies else None,
            "invalid_date_count": (
                stats.invalid_date_count if name in source.date_fields else None
            ),
            "suspicious_date_count": (
                stats.suspicious_date_count if name in source.date_fields else None
            ),
            "suspicious_date_examples": (
                sorted(stats.suspicious_date_examples or ()) if name in source.date_fields else None
            ),
        }

    created_at = datetime.now(UTC)
    payload = {
        "profile_version": 1,
        "created_at": created_at.isoformat(),
        "source_slug": source.slug,
        "dataset_id": source.dataset_id,
        "artifact": str(artifact.relative_to(root)),
        "row_count": row_count,
        "expected_minimum_rows": source.expected_minimum_rows,
        "meets_expected_minimum": row_count >= source.expected_minimum_rows,
        "missing_configured_fields": missing_configured_fields,
        "duplicate_counts_for_candidate_keys": duplicate_counts,
        "fields": observed_fields,
        "null_definition": "empty or whitespace-only CSV value",
    }
    output_dir = root / "reports" / "profiles"
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"{timestamp_for_path(created_at)}-{source.slug}.json"
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output


def summarize_profiles(paths: list[Path]) -> str:
    rows = []
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows.append(
            (
                payload["source_slug"],
                payload["row_count"],
                payload["meets_expected_minimum"],
                len(payload["missing_configured_fields"]),
            )
        )
    lines = [
        "| Source | Rows | Minimum met | Missing configured fields |",
        "|---|---:|:---:|---:|",
    ]
    lines.extend(
        f"| {source} | {count:,} | {'yes' if minimum else 'no'} | {missing} |"
        for source, count, minimum, missing in rows
    )
    return "\n".join(lines)
