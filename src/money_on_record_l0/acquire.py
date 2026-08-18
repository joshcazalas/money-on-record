from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .contracts import SourceContract

_CHUNK_BYTES = 1024 * 1024
_USER_AGENT = "money-on-record-l0/0.1 (public-interest data research)"


class AcquisitionError(RuntimeError):
    """A source could not be acquired or failed basic integrity checks."""


@dataclass(frozen=True)
class DownloadReceipt:
    requested_url: str
    response_url: str
    status: int
    retrieved_at: str
    sha256: str
    bytes: int
    response_headers: dict[str, str]


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def utc_now() -> datetime:
    return datetime.now(UTC)


def timestamp_for_path(value: datetime) -> str:
    return value.strftime("%Y%m%dT%H%M%SZ")


def _request_headers() -> dict[str, str]:
    headers = {"Accept": "*/*", "User-Agent": _USER_AGENT}
    app_token = os.environ.get("AUSTIN_SOCRATA_APP_TOKEN")
    if app_token:
        headers["X-App-Token"] = app_token
    return headers


def download_to_temp(url: str, staging_dir: Path) -> tuple[Path, DownloadReceipt]:
    staging_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    total_bytes = 0
    retrieved_at = utc_now()
    request = urllib.request.Request(url, headers=_request_headers())
    temporary: Path | None = None

    try:
        with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310
            status = int(getattr(response, "status", 200))
            if status != 200:
                raise AcquisitionError(f"GET {url} returned HTTP {status}")
            with tempfile.NamedTemporaryFile(dir=staging_dir, delete=False) as handle:
                temporary = Path(handle.name)
                while chunk := response.read(_CHUNK_BYTES):
                    digest.update(chunk)
                    total_bytes += len(chunk)
                    handle.write(chunk)
            receipt = DownloadReceipt(
                requested_url=url,
                response_url=response.geturl(),
                status=status,
                retrieved_at=retrieved_at.isoformat(),
                sha256=digest.hexdigest(),
                bytes=total_bytes,
                response_headers={key.casefold(): value for key, value in response.headers.items()},
            )
    except (TimeoutError, urllib.error.URLError) as exc:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise AcquisitionError(f"GET {url} failed: {exc}") from exc
    except Exception:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise

    if temporary is None or total_bytes == 0:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise AcquisitionError(f"GET {url} returned an empty response")
    return temporary, receipt


def _commit_content_addressed(temporary: Path, target_dir: Path, suffix: str, sha256: str) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{sha256}{suffix}"
    if target.exists():
        temporary.unlink()
    else:
        shutil.move(str(temporary), target)
    return target


def _write_manifest(
    *,
    operation: str,
    source: SourceContract,
    artifact: Path,
    receipt: DownloadReceipt,
    root: Path,
    details: dict[str, Any] | None = None,
) -> Path:
    manifest_dir = root / "data" / "manifests"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    stamp = timestamp_for_path(datetime.fromisoformat(receipt.retrieved_at))
    manifest_path = manifest_dir / f"{stamp}-{operation}-{source.slug}-{receipt.sha256[:12]}.json"
    payload: dict[str, Any] = {
        "manifest_version": 1,
        "operation": operation,
        "source_slug": source.slug,
        "dataset_id": source.dataset_id,
        "title": source.title,
        "artifact": str(artifact.relative_to(root)),
        "receipt": asdict(receipt),
    }
    if details:
        payload["details"] = details
    manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest_path


def freeze_metadata(source: SourceContract, root: Path | None = None) -> Path:
    root = root or project_root()
    temporary, receipt = download_to_temp(source.metadata_url, root / "data" / ".staging")
    try:
        metadata = json.loads(temporary.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        temporary.unlink(missing_ok=True)
        raise AcquisitionError(f"{source.slug}: metadata was not valid UTF-8 JSON") from exc

    actual_id = metadata.get("id")
    if actual_id != source.dataset_id:
        temporary.unlink(missing_ok=True)
        raise AcquisitionError(
            f"{source.slug}: expected dataset {source.dataset_id}, "
            f"metadata identified {actual_id!r}"
        )
    artifact = _commit_content_addressed(
        temporary,
        root / "data" / "metadata" / source.dataset_id,
        ".json",
        receipt.sha256,
    )
    return _write_manifest(
        operation="freeze-metadata",
        source=source,
        artifact=artifact,
        receipt=receipt,
        root=root,
        details={
            "rows_updated_at": metadata.get("rowsUpdatedAt"),
            "publication_date": metadata.get("publicationDate"),
            "view_last_modified": metadata.get("viewLastModified"),
            "columns": len(metadata.get("columns", [])),
        },
    )


def acquire_csv(source: SourceContract, root: Path | None = None) -> Path:
    root = root or project_root()
    temporary, receipt = download_to_temp(source.bulk_csv_url, root / "data" / ".staging")
    with temporary.open("rb") as handle:
        first_line = handle.readline(256 * 1024)
    if b"," not in first_line or b"\n" not in first_line:
        temporary.unlink(missing_ok=True)
        raise AcquisitionError(f"{source.slug}: response did not have a recognizable CSV header")

    artifact = _commit_content_addressed(
        temporary,
        root / "data" / "raw" / source.dataset_id,
        ".csv",
        receipt.sha256,
    )
    return _write_manifest(
        operation="acquire-csv",
        source=source,
        artifact=artifact,
        receipt=receipt,
        root=root,
    )


def latest_artifact(source: SourceContract, operation: str, root: Path | None = None) -> Path:
    root = root or project_root()
    manifests = root / "data" / "manifests"
    matches: list[tuple[str, Path]] = []
    for path in manifests.glob(f"*-{operation}-{source.slug}-*.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        matches.append((payload["receipt"]["retrieved_at"], root / payload["artifact"]))
    if not matches:
        raise AcquisitionError(f"{source.slug}: no {operation} manifest found; acquire it first")
    artifact = max(matches, key=lambda match: match[0])[1]
    if not artifact.is_file():
        raise AcquisitionError(f"manifest references missing artifact: {artifact}")
    return artifact


def verify_artifacts(root: Path | None = None) -> int:
    root = root or project_root()
    manifests = sorted((root / "data" / "manifests").glob("*.json"))
    if not manifests:
        raise AcquisitionError("no acquisition manifests found")
    verified = 0
    for manifest in manifests:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        artifact = root / payload["artifact"]
        if not artifact.is_file():
            raise AcquisitionError(f"{manifest.name}: artifact is missing: {artifact}")
        digest = hashlib.sha256()
        byte_count = 0
        with artifact.open("rb") as handle:
            while chunk := handle.read(_CHUNK_BYTES):
                digest.update(chunk)
                byte_count += len(chunk)
        expected_hash = payload["receipt"]["sha256"]
        expected_bytes = payload["receipt"]["bytes"]
        if digest.hexdigest() != expected_hash or byte_count != expected_bytes:
            raise AcquisitionError(f"{manifest.name}: integrity mismatch for {payload['artifact']}")
        verified += 1
    return verified
