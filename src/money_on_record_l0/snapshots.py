"""Publish validated browser builds as immutable, independently restorable snapshots.

This is the publication boundary for #30. It consumes the reviewed browser
selection; fresh acquisition and its quality gates remain upstream work.
"""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
import uuid
import zipfile
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .contracts import load_inventory
from .record_browser import ROOT, source_catalog
from .site import MAX_ARCHIVE_BYTES, build_site, verify_site_archive
from .snapshot_store import SnapshotError, Store, StoredValue, put_blob
from .versioned import validate_versioned_data

TRANSFORM_VERSION = "record-browser/1"
SNAPSHOT_ID = re.compile(r"[0-9]{8}T[0-9]{6}Z-[a-f0-9]{64}\Z")
SHA256 = re.compile(r"[a-f0-9]{64}\Z")
COMMIT = re.compile(r"[a-f0-9]{40}\Z")
MANIFEST_LIMIT = 128 * 1024


def encode(document: Any) -> bytes:
    return (
        json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode()


def _decode(data: bytes) -> Any:
    try:
        return json.loads(data)
    except ValueError, UnicodeError:
        raise SnapshotError("invalid_snapshot_json") from None


def _utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
        offset = parsed.utcoffset()
        if offset is None or offset.total_seconds() != 0:
            raise ValueError
        return parsed.astimezone(UTC)
    except ValueError, AttributeError, TypeError:
        raise SnapshotError("invalid_snapshot_timestamp") from None


def _write_document(store: Store, key: str, document: dict[str, Any], work: Path) -> bytes:
    data = encode(document)
    path = work / "document.json"
    path.write_bytes(data)
    store.create(key, path)
    return data


def _lineage() -> list[dict[str, Any]]:
    """Select acquisition receipts by content hash, never by a latest-file guess."""
    inventory = load_inventory()
    validate_versioned_data(inventory, root=ROOT)
    receipts = [json.loads(path.read_bytes()) for path in (ROOT / "data/manifests").glob("*.json")]
    lineage = []
    for entry in source_catalog():
        source = inventory.require(entry["slug"])
        raw_matches = [
            item
            for item in receipts
            if item["operation"] == "acquire-csv"
            and item["dataset_id"] == source.dataset_id
            and item["receipt"]["sha256"] == entry["sha256"]
        ]
        if not raw_matches:
            raise SnapshotError("source_receipt_missing")
        raw = max(raw_matches, key=lambda item: _utc(item["receipt"]["retrieved_at"]))["receipt"]
        metadata_matches = [
            item
            for item in receipts
            if item["operation"] == "freeze-metadata"
            and item["dataset_id"] == source.dataset_id
            and _utc(item["receipt"]["retrieved_at"]) <= _utc(raw["retrieved_at"])
        ]
        if not metadata_matches:
            raise SnapshotError("source_metadata_missing")
        metadata_receipt = max(
            metadata_matches, key=lambda item: _utc(item["receipt"]["retrieved_at"])
        )["receipt"]
        metadata_path = (
            ROOT / "data/metadata" / source.dataset_id / (metadata_receipt["sha256"] + ".json")
        )
        metadata = json.loads(metadata_path.read_bytes())
        schema = [
            {field: column.get(field) for field in ("fieldName", "name", "dataTypeName")}
            for column in metadata["columns"]
        ]
        lineage.append(
            {
                "slug": source.slug,
                "dataset_id": source.dataset_id,
                "request_url": source.bulk_csv_url,
                "retrieved_at": raw["retrieved_at"],
                "raw": {"sha256": raw["sha256"], "bytes": raw["bytes"]},
                "metadata": {
                    "sha256": metadata_receipt["sha256"],
                    "bytes": metadata_receipt["bytes"],
                    "retrieved_at": metadata_receipt["retrieved_at"],
                },
                "schema_sha256": hashlib.sha256(encode(schema)).hexdigest(),
                "source_updated_at": metadata.get("rowsUpdatedAt"),
                "row_count": entry["row_count"],
            }
        )
    return sorted(lineage, key=lambda item: item["slug"])


def read_current(store: Store) -> tuple[dict[str, Any] | None, StoredValue | None]:
    current = store.read("current.json", limit=4096)
    if current is None:
        return None, None
    document = _decode(current.data)
    if (
        not isinstance(document, dict)
        or set(document) != {"schema_version", "snapshot_id", "generation", "published_at"}
        or document["schema_version"] != 1
        or not isinstance(document["snapshot_id"], str)
        or not SNAPSHOT_ID.fullmatch(document["snapshot_id"])
        or not isinstance(document["generation"], str)
        or not re.fullmatch(r"[a-f0-9]{32}", document["generation"])
    ):
        raise SnapshotError("invalid_current_pointer")
    _utc(document["published_at"])
    return document, current


def verify_snapshot(
    store: Store, snapshot_id: str, *, output: Path | None = None
) -> dict[str, Any]:
    if not SNAPSHOT_ID.fullmatch(snapshot_id):
        raise SnapshotError("invalid_snapshot_id")
    stored = store.read(f"snapshots/{snapshot_id}.json", limit=MANIFEST_LIMIT)
    if stored is None:
        raise SnapshotError("snapshot_missing")
    if hashlib.sha256(stored.data).hexdigest() != snapshot_id.split("-", 1)[1]:
        raise SnapshotError("snapshot_digest_mismatch")
    manifest = _decode(stored.data)
    if (
        not isinstance(manifest, dict)
        or set(manifest)
        != {
            "schema_version",
            "acquisition_completed_at",
            "transform_version",
            "code_revision",
            "archive",
            "sources",
            "files",
            "validation",
            "raw_storage",
        }
        or manifest["schema_version"] != 1
        or manifest["transform_version"] != TRANSFORM_VERSION
        or manifest["validation"] != "reviewed-browser-selection-v1"
        or manifest["raw_storage"] != "external-lineage-only"
        or not isinstance(manifest["code_revision"], str)
        or not COMMIT.fullmatch(manifest["code_revision"])
    ):
        raise SnapshotError("invalid_snapshot_manifest")
    stamp = _utc(manifest["acquisition_completed_at"]).strftime("%Y%m%dT%H%M%SZ")
    if stamp != snapshot_id.split("-", 1)[0]:
        raise SnapshotError("snapshot_timestamp_mismatch")
    reference = manifest["archive"]
    if (
        not isinstance(reference, dict)
        or set(reference) != {"key", "sha256", "bytes"}
        or not isinstance(reference["sha256"], str)
        or not SHA256.fullmatch(reference["sha256"])
        or reference["key"] != f"site/{reference['sha256']}"
        or type(reference["bytes"]) is not int
        or not 0 < reference["bytes"] <= MAX_ARCHIVE_BYTES
    ):
        raise SnapshotError("invalid_archive_reference")
    archive = store.read(reference["key"], limit=MAX_ARCHIVE_BYTES)
    if archive is None:
        raise SnapshotError("snapshot_archive_missing")
    if (
        len(archive.data) != reference["bytes"]
        or hashlib.sha256(archive.data).hexdigest() != reference["sha256"]
    ):
        raise SnapshotError("snapshot_archive_corrupt")
    with tempfile.TemporaryDirectory(prefix="mor-verify-") as temporary:
        path = Path(temporary) / "site.zip"
        path.write_bytes(archive.data)
        try:
            verify_site_archive(path, expected_sha256=reference["sha256"])
            with zipfile.ZipFile(path) as archive_file:
                site_manifest = json.loads(archive_file.read("site-manifest.json"))
                catalog = json.loads(archive_file.read("_data/sources.json"))
            sources = manifest["sources"]
            if (
                not isinstance(sources, list)
                or not isinstance(catalog, list)
                or not sources
                or len(sources) != len(catalog)
                or len({source["slug"] for source in sources}) != len(sources)
                or {source["slug"] for source in sources} != {entry["slug"] for entry in catalog}
                or sorted(source["raw"]["sha256"] for source in sources)
                != site_manifest["source_snapshots"]
                or any(
                    not any(
                        entry["slug"] == source["slug"]
                        and entry["dataset_id"] == source["dataset_id"]
                        and entry["row_count"] == source["row_count"]
                        and entry["sha256"] == source["raw"]["sha256"]
                        for entry in catalog
                    )
                    for source in sources
                )
                or manifest["files"] != site_manifest["files"]
                or max(_utc(source["retrieved_at"]) for source in sources)
                != _utc(manifest["acquisition_completed_at"])
            ):
                raise SnapshotError("snapshot_lineage_mismatch")
            if output is not None:
                verify_site_archive(path, expected_sha256=reference["sha256"], output=output)
        except ValueError, OSError, KeyError, TypeError, zipfile.BadZipFile:
            raise SnapshotError("snapshot_archive_invalid") from None
    return manifest


def _advance(store: Store, snapshot_id: str, previous: StoredValue | None) -> None:
    # A nonce prevents an A -> B -> A rollback from reviving an obsolete writer.
    pointer = {
        "schema_version": 1,
        "snapshot_id": snapshot_id,
        "generation": uuid.uuid4().hex,
        "published_at": datetime.now(UTC).isoformat(),
    }
    store.replace_current(encode(pointer), expected=previous.revision if previous else None)


def publish_snapshot(store: Store, *, content_path: Path, code_revision: str) -> str:
    """Build, validate twice, persist, verify readback, then conditionally publish."""
    if not COMMIT.fullmatch(code_revision):
        raise SnapshotError("invalid_code_revision")
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex
    phase = "read_current"
    with tempfile.TemporaryDirectory(prefix="mor-publish-") as temporary:
        work = Path(temporary)
        try:
            current, previous = read_current(store)
            phase = "validate_build"
            sources = _lineage()
            artifacts = []
            for attempt in ("one", "two"):
                archive = work / f"{attempt}.zip"
                artifacts.append(
                    build_site(
                        content_path=content_path,
                        output=work / attempt,
                        archive=archive,
                        checksum=work / f"{attempt}.sha256",
                    )
                )
            if artifacts[0] != artifacts[1]:
                raise SnapshotError("nondeterministic_build")
            phase = "store_archive"
            archive_reference = put_blob(store, "site", work / "one.zip")
            build_manifest = json.loads((work / "one/site-manifest.json").read_bytes())
            acquired = max(_utc(source["retrieved_at"]) for source in sources).isoformat()
            manifest = {
                "schema_version": 1,
                "acquisition_completed_at": acquired,
                "transform_version": TRANSFORM_VERSION,
                "code_revision": code_revision,
                "archive": archive_reference,
                "sources": sources,
                "files": build_manifest["files"],
                "validation": "reviewed-browser-selection-v1",
                "raw_storage": "external-lineage-only",
            }
            digest = hashlib.sha256(encode(manifest)).hexdigest()
            snapshot_id = _utc(acquired).strftime("%Y%m%dT%H%M%SZ") + "-" + digest
            phase = "store_manifest"
            _write_document(store, f"snapshots/{snapshot_id}.json", manifest, work)
            phase = "verify_stored_snapshot"
            verify_snapshot(store, snapshot_id)
            phase = "advance_current"
            if current is not None and current["snapshot_id"] == snapshot_id:
                # Idempotent replay must still detect a concurrent publication/rollback.
                _, latest = read_current(store)
                if latest is None or previous is None or latest.revision != previous.revision:
                    raise SnapshotError("current_pointer_conflict")
            else:
                _advance(store, snapshot_id, previous)
            return snapshot_id
        except Exception as error:
            code = error.code if isinstance(error, SnapshotError) else "snapshot_publication_failed"
            report = {
                "schema_version": 1,
                "run_id": run_id,
                "phase": phase,
                "code": code,
                "publication_status": "indeterminate"
                if phase == "advance_current"
                else "unchanged",
            }
            # Preserve the primary failure if the same outage also blocks quarantine.
            with suppress(Exception):
                _write_document(store, f"runs/{run_id}/failure.json", report, work)
            raise SnapshotError(code) from None


def restore_snapshot(store: Store, snapshot_id: str, *, expected_current: str) -> None:
    current, previous = read_current(store)
    if current is None or current["snapshot_id"] != expected_current:
        raise SnapshotError("current_pointer_conflict")
    verify_snapshot(store, snapshot_id)
    _advance(store, snapshot_id, previous)
