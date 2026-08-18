from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .contracts import Inventory
from .privacy import scan_public_csv
from .review import ReviewError, validate_review_summary


class VersionedDataError(ValueError):
    """A checked-in data artifact violates the repository contract."""


@dataclass(frozen=True)
class VersionedDataSummary:
    manifests: int
    metadata_artifacts: int
    profiles: int
    fixtures: int
    review_summaries: int


def _object_from_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VersionedDataError(f"{path}: expected valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise VersionedDataError(f"{path}: expected a JSON object")
    return value


def _relative_artifact(value: object, *, manifest: Path) -> Path:
    if not isinstance(value, str) or not value:
        raise VersionedDataError(f"{manifest}: artifact must be a non-empty path")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise VersionedDataError(f"{manifest}: artifact must remain inside the repository")
    return path


def _sha256(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    byte_count = 0
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
            byte_count += len(chunk)
    return digest.hexdigest(), byte_count


def validate_versioned_data(
    inventory: Inventory,
    *,
    root: Path,
) -> VersionedDataSummary:
    """Validate the safe, offline data artifacts committed to the repository."""
    manifest_paths = sorted((root / "data" / "manifests").glob("*.json"))
    if not manifest_paths:
        raise VersionedDataError("data/manifests: no acquisition manifests found")

    metadata_sources: set[str] = set()
    acquisitions: set[tuple[str, str]] = set()
    metadata_count = 0

    for manifest_path in manifest_paths:
        payload = _object_from_json(manifest_path)
        if payload.get("manifest_version") != 1:
            raise VersionedDataError(f"{manifest_path}: unsupported manifest_version")

        slug = payload.get("source_slug")
        if not isinstance(slug, str):
            raise VersionedDataError(f"{manifest_path}: source_slug must be a string")
        source = inventory.require(slug)
        if payload.get("dataset_id") != source.dataset_id:
            raise VersionedDataError(f"{manifest_path}: dataset_id disagrees with inventory")

        receipt = payload.get("receipt")
        if not isinstance(receipt, dict):
            raise VersionedDataError(f"{manifest_path}: receipt must be an object")
        digest = receipt.get("sha256")
        byte_count = receipt.get("bytes")
        if not isinstance(digest, str) or len(digest) != 64:
            raise VersionedDataError(f"{manifest_path}: receipt has an invalid SHA-256")
        if not isinstance(byte_count, int) or byte_count <= 0:
            raise VersionedDataError(f"{manifest_path}: receipt has an invalid byte count")

        artifact = _relative_artifact(payload.get("artifact"), manifest=manifest_path)
        if artifact.stem != digest:
            raise VersionedDataError(f"{manifest_path}: artifact name must equal its SHA-256")

        operation = payload.get("operation")
        if operation == "freeze-metadata":
            expected_parent = Path("data") / "metadata" / source.dataset_id
            if artifact.parent != expected_parent or artifact.suffix != ".json":
                raise VersionedDataError(f"{manifest_path}: unexpected metadata artifact path")
            full_path = root / artifact
            if not full_path.is_file():
                raise VersionedDataError(f"{manifest_path}: versioned metadata is missing")
            actual_hash, actual_bytes = _sha256(full_path)
            if (actual_hash, actual_bytes) != (digest, byte_count):
                raise VersionedDataError(f"{manifest_path}: metadata integrity mismatch")
            metadata = _object_from_json(full_path)
            if metadata.get("id") != source.dataset_id:
                raise VersionedDataError(f"{full_path}: metadata identifies another dataset")
            metadata_sources.add(slug)
            metadata_count += 1
        elif operation == "acquire-csv":
            expected_parent = Path("data") / "raw" / source.dataset_id
            if artifact.parent != expected_parent or artifact.suffix != ".csv":
                raise VersionedDataError(f"{manifest_path}: unexpected raw artifact path")
            acquisitions.add((slug, str(artifact)))
        else:
            raise VersionedDataError(f"{manifest_path}: unsupported operation {operation!r}")

    missing_metadata = sorted(set(inventory.sources) - metadata_sources)
    if missing_metadata:
        raise VersionedDataError(f"no versioned metadata for: {', '.join(missing_metadata)}")

    profile_paths = sorted((root / "reports" / "profiles").glob("*.json"))
    profiled_sources: set[str] = set()
    for profile_path in profile_paths:
        profile = _object_from_json(profile_path)
        if profile.get("profile_version") != 1:
            raise VersionedDataError(f"{profile_path}: unsupported profile_version")
        slug = profile.get("source_slug")
        if not isinstance(slug, str):
            raise VersionedDataError(f"{profile_path}: source_slug must be a string")
        source = inventory.require(slug)
        if profile.get("dataset_id") != source.dataset_id:
            raise VersionedDataError(f"{profile_path}: dataset_id disagrees with inventory")
        if profile.get("expected_minimum_rows") != source.expected_minimum_rows:
            raise VersionedDataError(f"{profile_path}: expected row floor disagrees with inventory")
        row_count = profile.get("row_count")
        if not isinstance(row_count, int) or row_count < 0:
            raise VersionedDataError(f"{profile_path}: row_count must be non-negative")
        expected_result = row_count >= source.expected_minimum_rows
        if profile.get("meets_expected_minimum") is not expected_result:
            raise VersionedDataError(f"{profile_path}: row-floor result is internally inconsistent")
        artifact = profile.get("artifact")
        if not isinstance(artifact, str) or (slug, artifact) not in acquisitions:
            raise VersionedDataError(f"{profile_path}: raw artifact has no matching manifest")
        profiled_sources.add(slug)

    missing_profiles = sorted(set(inventory.sources) - profiled_sources)
    if missing_profiles:
        raise VersionedDataError(f"no aggregate profile for: {', '.join(missing_profiles)}")

    fixture_count = 0
    for source in inventory.sources.values():
        fixture = root / "fixtures" / "generated" / f"{source.slug}.csv"
        if not fixture.is_file():
            raise VersionedDataError(f"{fixture}: required redacted fixture is missing")
        findings = scan_public_csv(fixture, source)
        if findings:
            raise VersionedDataError(
                f"{fixture}: privacy scan found {len(findings)} potential PII value(s)"
            )
        fixture_count += 1

    review_summary_paths = sorted((root / "reports" / "reviews").glob("*.json"))
    for review_summary_path in review_summary_paths:
        try:
            validate_review_summary(review_summary_path)
        except ReviewError as exc:
            raise VersionedDataError(str(exc)) from exc

    return VersionedDataSummary(
        manifests=len(manifest_paths),
        metadata_artifacts=metadata_count,
        profiles=len(profile_paths),
        fixtures=fixture_count,
        review_summaries=len(review_summary_paths),
    )
