from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from yaml.nodes import MappingNode
from yaml.resolver import BaseResolver


class ContractError(ValueError):
    """Raised when the source inventory is missing required contract data."""


class _UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(
    loader: _UniqueKeyLoader,
    node: MappingNode,
    deep: bool = False,
) -> dict[Any, Any]:
    loader.flatten_mapping(node)
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise ContractError(f"duplicate YAML key: {key!r}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(
    BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


@dataclass(frozen=True)
class SourceContract:
    slug: str
    dataset_id: str
    title: str
    role: str
    metadata_url: str
    bulk_csv_url: str
    expected_minimum_rows: int
    identity_fields: tuple[str, ...]
    categorical_fields: tuple[str, ...]
    date_fields: tuple[str, ...]
    amount_fields: tuple[str, ...]
    candidate_amount_field: str | None
    uniqueness_fields: tuple[str, ...]
    public_fields: tuple[str, ...]
    restricted_fields: tuple[str, ...]
    restricted_field_patterns: tuple[str, ...]
    organization_name_field: str | None
    organization_type_field: str | None
    organization_type_values: tuple[str, ...]
    organization_code_field: str | None
    invalid_code_prefixes: tuple[str, ...]

    @classmethod
    def from_mapping(cls, slug: str, raw: dict[str, Any]) -> SourceContract:
        required = (
            "dataset_id",
            "title",
            "role",
            "metadata_url",
            "bulk_csv_url",
            "expected_minimum_rows",
            "public_fields",
        )
        missing = [field for field in required if field not in raw]
        if missing:
            raise ContractError(f"{slug}: missing required fields: {', '.join(missing)}")

        def values(name: str) -> tuple[str, ...]:
            return tuple(str(item) for item in raw.get(name, ()))

        return cls(
            slug=slug,
            dataset_id=str(raw["dataset_id"]),
            title=str(raw["title"]),
            role=str(raw["role"]),
            metadata_url=str(raw["metadata_url"]),
            bulk_csv_url=str(raw["bulk_csv_url"]),
            expected_minimum_rows=int(raw["expected_minimum_rows"]),
            identity_fields=values("identity_fields"),
            categorical_fields=values("categorical_fields"),
            date_fields=values("date_fields"),
            amount_fields=values("amount_fields"),
            candidate_amount_field=raw.get("candidate_amount_field"),
            uniqueness_fields=values("uniqueness_fields"),
            public_fields=values("public_fields"),
            restricted_fields=values("restricted_fields"),
            restricted_field_patterns=values("restricted_field_patterns"),
            organization_name_field=raw.get("organization_name_field"),
            organization_type_field=raw.get("organization_type_field"),
            organization_type_values=values("organization_type_values"),
            organization_code_field=raw.get("organization_code_field"),
            invalid_code_prefixes=values("invalid_code_prefixes"),
        )


@dataclass(frozen=True)
class Inventory:
    version: int
    portal: str
    publisher: str
    sources: dict[str, SourceContract]

    def require(self, slug: str) -> SourceContract:
        try:
            return self.sources[slug]
        except KeyError as exc:
            choices = ", ".join(sorted(self.sources))
            raise ContractError(f"unknown source {slug!r}; choose one of: {choices}") from exc


def default_inventory_path() -> Path:
    return Path(__file__).resolve().parents[2] / "config" / "sources.yaml"


def load_inventory(path: Path | None = None) -> Inventory:
    inventory_path = path or default_inventory_path()
    with inventory_path.open(encoding="utf-8") as handle:
        raw = yaml.load(handle, Loader=_UniqueKeyLoader)

    if not isinstance(raw, dict) or not isinstance(raw.get("sources"), dict):
        raise ContractError(f"{inventory_path}: expected a sources mapping")

    sources = {
        slug: SourceContract.from_mapping(slug, source) for slug, source in raw["sources"].items()
    }
    dataset_ids = [source.dataset_id for source in sources.values()]
    if len(dataset_ids) != len(set(dataset_ids)):
        raise ContractError("dataset_id values must be unique")
    for source in sources.values():
        if len(source.public_fields) != len(set(source.public_fields)):
            raise ContractError(f"{source.slug}: public_fields contains duplicates")
        if len(source.restricted_fields) != len(set(source.restricted_fields)):
            raise ContractError(f"{source.slug}: restricted_fields contains duplicates")
        overlap = sorted(set(source.public_fields) & set(source.restricted_fields))
        if overlap:
            raise ContractError(
                f"{source.slug}: fields cannot be public and restricted: {', '.join(overlap)}"
            )
        if (
            source.candidate_amount_field
            and source.candidate_amount_field not in source.amount_fields
        ):
            raise ContractError(
                f"{source.slug}: candidate_amount_field must be declared in amount_fields"
            )

    return Inventory(
        version=int(raw["version"]),
        portal=str(raw["portal"]),
        publisher=str(raw["publisher"]),
        sources=sources,
    )
