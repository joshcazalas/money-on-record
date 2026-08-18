from __future__ import annotations

import re
import unicodedata

_NON_ALPHANUMERIC = re.compile(r"[^A-Z0-9]+")
_WHITESPACE = re.compile(r"\s+")
_DOTTED_ACRONYM = re.compile(r"(?:\b[A-Z]\.){2,}[A-Z]?\.?")
_LEGAL_SUFFIXES = {
    "ASSN",
    "ASSOCIATION",
    "CO",
    "COMPANY",
    "CORP",
    "CORPORATION",
    "INC",
    "INCORPORATED",
    "LC",
    "LLC",
    "LLP",
    "LP",
    "LTD",
    "LIMITED",
    "PA",
    "PC",
    "PLLC",
}


def strict_name_key(value: str) -> str:
    """Normalize typography while preserving identity-bearing legal suffixes."""
    ascii_value = (
        unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii").upper()
    )
    ascii_value = _DOTTED_ACRONYM.sub(lambda match: match.group().replace(".", ""), ascii_value)
    ascii_value = ascii_value.replace("&", " AND ")
    return _WHITESPACE.sub(" ", _NON_ALPHANUMERIC.sub(" ", ascii_value)).strip()


def suffix_candidate_key(value: str) -> str:
    """Remove trailing legal suffixes for candidate generation, never auto-linking."""
    tokens = strict_name_key(value).split()
    while tokens and tokens[-1] in _LEGAL_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def has_invalid_code_prefix(value: str, prefixes: tuple[str, ...]) -> bool:
    normalized = value.strip().upper()
    return any(normalized.startswith(prefix.upper()) for prefix in prefixes)
