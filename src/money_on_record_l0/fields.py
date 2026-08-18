from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

_NON_FIELD_CHARACTER = re.compile(r"[^a-z0-9]+")


def canonical_field_name(value: str) -> str:
    """Convert Socrata display or API field names to one stable local spelling."""
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return _NON_FIELD_CHARACTER.sub("_", normalized.casefold()).strip("_")


def canonical_header(fieldnames: Iterable[str | None]) -> dict[str, str]:
    """Return canonical -> source header mapping and reject ambiguous columns."""
    result: dict[str, str] = {}
    for source_name in fieldnames:
        if source_name is None:
            continue
        canonical = canonical_field_name(source_name)
        if not canonical:
            raise ValueError(f"empty canonical header produced by {source_name!r}")
        if canonical in result:
            raise ValueError(
                f"headers {result[canonical]!r} and {source_name!r} both map to {canonical!r}"
            )
        result[canonical] = source_name
    return result
