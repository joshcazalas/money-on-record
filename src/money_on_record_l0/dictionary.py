from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .acquire import latest_artifact, project_root
from .contracts import SourceContract
from .fields import canonical_field_name


def classify_field(field: str, source: SourceContract) -> str:
    if field in source.public_fields:
        return "PUBLIC_ALLOWLISTED"
    if field in source.restricted_fields or any(
        pattern.casefold() in field.casefold() for pattern in source.restricted_field_patterns
    ):
        return "RESTRICTED"
    return "INTERNAL_REVIEW"


def write_field_dictionary(source: SourceContract, root: Path | None = None) -> Path:
    root = root or project_root()
    artifact = latest_artifact(source, "freeze-metadata", root)
    metadata = json.loads(artifact.read_text(encoding="utf-8"))
    columns: list[dict[str, Any]] = metadata.get("columns", [])
    output_dir = root / "docs" / "field-dictionaries"
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"{source.slug}.md"

    observed = {
        canonical_field_name(str(column.get("fieldName") or column.get("name") or ""))
        for column in columns
    }
    configured = set(
        source.public_fields
        + source.identity_fields
        + source.categorical_fields
        + source.date_fields
        + source.amount_fields
        + source.uniqueness_fields
    )
    missing = sorted(configured - observed)
    lines = [
        f"# {source.title}",
        "",
        f"- Dataset ID: `{source.dataset_id}`",
        f"- Role: `{source.role}`",
        f"- Frozen metadata: `{artifact.relative_to(root)}`",
        "- Publication rule: default deny; only `PUBLIC_ALLOWLISTED` fields may "
        "leave the pipeline.",
        "",
    ]
    if missing:
        lines.extend(
            [
                "## Contract discrepancies",
                "",
                "Configured fields not present in the frozen metadata:",
                "",
                *[f"- `{field}`" for field in missing],
                "",
            ]
        )
    lines.extend(
        [
            "## Fields",
            "",
            "| API field | Display name | Socrata type | Classification | Description |",
            "|---|---|---|---|---|",
        ]
    )
    for column in columns:
        api_field = canonical_field_name(str(column.get("fieldName") or column.get("name") or ""))
        description = str(column.get("description") or "").replace("|", "\\|").replace("\n", " ")
        display_name = str(column.get("name") or "").replace("|", "\\|")
        data_type = str(column.get("dataTypeName") or "")
        lines.append(
            f"| `{api_field}` | {display_name} | `{data_type}` | "
            f"`{classify_field(api_field, source)}` | {description} |"
        )
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output
