from __future__ import annotations

import csv
from pathlib import Path

from .acquire import latest_artifact, project_root
from .contracts import SourceContract
from .privacy import scan_public_csv
from .source_schema import resolved_source_header


def create_redacted_fixture(
    source: SourceContract,
    *,
    rows: int = 20,
    root: Path | None = None,
) -> Path:
    """Create a schema/null-shape fixture containing none of the source values."""
    root = root or project_root()
    artifact = latest_artifact(source, "acquire-csv", root)
    output_dir = root / "fixtures" / "generated"
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"{source.slug}.csv"

    with artifact.open(encoding="utf-8-sig", newline="") as input_handle:
        reader = csv.DictReader(input_handle)
        if reader.fieldnames is None:
            raise ValueError(f"{artifact}: missing CSV header")
        header = resolved_source_header(reader.fieldnames, source, root)
        selected = [field for field in source.public_fields if field in header]
        with output.open("w", encoding="utf-8", newline="") as output_handle:
            writer = csv.DictWriter(output_handle, fieldnames=selected, lineterminator="\n")
            writer.writeheader()
            for index, row in enumerate(reader, start=1):
                if index > rows:
                    break
                writer.writerow(
                    {
                        field: _synthetic_value(
                            field=field,
                            source_value=row.get(header[field], ""),
                            row_number=index,
                            source=source,
                        )
                        for field in selected
                    }
                )

    findings = scan_public_csv(output, source)
    if findings:
        output.unlink(missing_ok=True)
        raise ValueError(f"generated fixture failed privacy scan with {len(findings)} finding(s)")
    return output


def _synthetic_value(
    *,
    field: str,
    source_value: str,
    row_number: int,
    source: SourceContract,
) -> str:
    if not source_value.strip():
        return ""
    if field in source.date_fields:
        return f"2000-01-{((row_number - 1) % 28) + 1:02d}T00:00:00.000"
    if field in source.amount_fields or field in {"quantity"}:
        return f"{row_number}.00"
    if "url" in field or field.startswith("link_") or field.startswith("view_"):
        return f"https://example.invalid/source-record/{row_number}"
    if field.endswith("_id") or field.endswith("_number") or field.endswith("_code"):
        return f"SYNTHETIC-{row_number:04d}"
    if field in source.identity_fields or field == source.organization_name_field:
        return f"EXAMPLE ORGANIZATION {row_number:04d}"
    return f"SYNTHETIC {field.upper()} {row_number:04d}"
