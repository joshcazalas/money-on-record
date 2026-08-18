from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .acquire import latest_artifact, project_root
from .contracts import SourceContract
from .fields import canonical_field_name


def metadata_field_map(columns: list[dict[str, Any]]) -> dict[str, str]:
    """Map canonical Socrata display headers to canonical API field names."""
    result: dict[str, str] = {}
    for column in columns:
        api_name = canonical_field_name(str(column.get("fieldName") or column.get("name") or ""))
        display_name = canonical_field_name(str(column.get("name") or api_name))
        for observed in {api_name, display_name}:
            existing = result.get(observed)
            if existing is not None and existing != api_name:
                raise ValueError(
                    f"metadata header {observed!r} maps to both {existing!r} and {api_name!r}"
                )
            result[observed] = api_name
    return result


def resolved_source_header(
    fieldnames: Iterable[str | None],
    source: SourceContract,
    root: Path | None = None,
) -> dict[str, str]:
    """Return API field -> raw CSV header using the frozen metadata dictionary."""
    root = root or project_root()
    artifact = latest_artifact(source, "freeze-metadata", root)
    metadata = json.loads(artifact.read_text(encoding="utf-8"))
    field_map = metadata_field_map(metadata.get("columns", []))
    result: dict[str, str] = {}
    for raw_name in fieldnames:
        if raw_name is None:
            continue
        raw_canonical = canonical_field_name(raw_name)
        api_name = field_map.get(raw_canonical, raw_canonical)
        if api_name in result:
            raise ValueError(
                f"headers {result[api_name]!r} and {raw_name!r} both resolve to {api_name!r}"
            )
        result[api_name] = raw_name
    return result
