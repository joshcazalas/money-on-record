"""Private snapshot storage with immutable objects and conditional pointer writes.

A store is dedicated to one environment. Only current.json is mutable. Local
locking is for processes on one host; S3 conditional writes coordinate tasks.
"""

from __future__ import annotations

import base64
import fcntl
import hashlib
import os
import re
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

KEY = re.compile(r"[a-zA-Z0-9_.-]+(?:/[a-zA-Z0-9_.-]+)*\Z")
MAX_OBJECT_BYTES = 5 * 1024**3
LAYERS = frozenset({"raw", "metadata", "normalized", "candidates", "resolved", "site"})


class SnapshotError(RuntimeError):
    """Safe, machine-readable error; never include source values or SDK errors."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class StoredValue:
    data: bytes
    revision: str


class Store(Protocol):
    def read(self, key: str, *, limit: int) -> StoredValue | None: ...
    def create(self, key: str, path: Path) -> None: ...
    def replace_current(self, data: bytes, *, expected: str | None) -> None: ...


def validate_key(key: str) -> None:
    if not KEY.fullmatch(key) or any(part in {".", ".."} for part in key.split("/")):
        raise SnapshotError("invalid_object_key")


def file_digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _check_file(path: Path) -> None:
    if not path.is_file() or path.is_symlink() or path.stat().st_size > MAX_OBJECT_BYTES:
        raise SnapshotError("invalid_object_file")


def _upload_digest(key: str, path: Path) -> str:
    digest = file_digest(path)
    layer, _, identifier = key.partition("/")
    if layer in LAYERS and re.fullmatch(r"[a-f0-9]{64}", identifier) and digest != identifier:
        raise SnapshotError("source_changed_during_upload")
    return digest


class LocalStore:
    def __init__(self, root: Path) -> None:
        if root.is_symlink():
            raise SnapshotError("unsafe_store_path")
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def _path(self, key: str) -> Path:
        validate_key(key)
        path = self.root / key
        if any(part.is_symlink() for part in (path, *path.parents)):
            raise SnapshotError("unsafe_store_path")
        return path

    @contextmanager
    def _lock(self) -> Iterator[None]:
        lock = self._path("store.lock")
        with lock.open("a+b") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            yield

    def read(self, key: str, *, limit: int) -> StoredValue | None:
        path = self._path(key)
        try:
            with path.open("rb") as handle:
                data = handle.read(limit + 1)
        except FileNotFoundError:
            return None
        if len(data) > limit:
            raise SnapshotError("object_too_large")
        return StoredValue(data, hashlib.sha256(data).hexdigest())

    def _write(
        self, target: Path, source: Path | bytes, *, expected_digest: str | None = None
    ) -> None:
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary: Path | None = None
        try:
            digest = hashlib.sha256()
            with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as handle:
                temporary = Path(handle.name)
                if isinstance(source, bytes):
                    handle.write(source)
                else:
                    with source.open("rb") as incoming:
                        while chunk := incoming.read(1024 * 1024):
                            handle.write(chunk)
                            digest.update(chunk)
                handle.flush()
                os.fsync(handle.fileno())
            if expected_digest is not None and digest.hexdigest() != expected_digest:
                raise SnapshotError("source_changed_during_upload")
            os.replace(temporary, target)
            directory = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def create(self, key: str, path: Path) -> None:
        if key == "current.json":
            raise SnapshotError("conditional_pointer_write_required")
        _check_file(path)
        with self._lock():
            target = self._path(key)
            digest = _upload_digest(key, path)
            if target.exists():
                if file_digest(target) != digest:
                    raise SnapshotError("immutable_object_conflict")
                return
            self._write(target, path, expected_digest=digest)

    def replace_current(self, data: bytes, *, expected: str | None) -> None:
        with self._lock():
            current = self.read("current.json", limit=4096)
            if (current.revision if current else None) != expected:
                raise SnapshotError("current_pointer_conflict")
            self._write(self._path("current.json"), data)


class S3Store:
    def __init__(self, *, bucket: str, account_id: str, prefix: str, client: Any = None) -> None:
        if not re.fullmatch(r"[0-9]{12}", account_id):
            raise SnapshotError("invalid_bucket_account")
        if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", bucket):
            raise SnapshotError("invalid_bucket_name")
        validate_key(prefix)
        self.bucket = bucket
        self.account_id = account_id
        self.prefix = prefix
        if client is None:
            try:
                import boto3
                from botocore.config import Config
            except ImportError:
                raise SnapshotError("s3_extra_required") from None
            client = boto3.client(
                "s3",
                config=Config(
                    connect_timeout=10,
                    read_timeout=120,
                    retries={"mode": "standard", "total_max_attempts": 4},
                ),
            )
        self.client = client

    def _args(self, key: str) -> dict[str, Any]:
        validate_key(key)
        return {
            "Bucket": self.bucket,
            "Key": f"{self.prefix}/{key}",
            "ExpectedBucketOwner": self.account_id,
        }

    @staticmethod
    def _status(error: Exception) -> int | None:
        return getattr(error, "response", {}).get("ResponseMetadata", {}).get("HTTPStatusCode")

    def read(self, key: str, *, limit: int) -> StoredValue | None:
        try:
            response = self.client.get_object(**self._args(key))
            body = response["Body"]
            try:
                data = body.read(limit + 1)
            finally:
                body.close()
            if len(data) > limit or response["ContentLength"] != len(data):
                raise SnapshotError("object_size_mismatch")
            return StoredValue(data, response["ETag"])
        except SnapshotError:
            raise
        except Exception as error:
            if self._status(error) == 404:
                return None
            raise SnapshotError("store_read_failed") from None

    def create(self, key: str, path: Path) -> None:
        if key == "current.json":
            raise SnapshotError("conditional_pointer_write_required")
        _check_file(path)
        checksum = base64.b64encode(bytes.fromhex(_upload_digest(key, path))).decode("ascii")
        try:
            with path.open("rb") as handle:
                self.client.put_object(
                    **self._args(key),
                    Body=handle,
                    ContentLength=path.stat().st_size,
                    ChecksumSHA256=checksum,
                    IfNoneMatch="*",
                    ServerSideEncryption="AES256",
                )
        except Exception as error:
            if self._status(error) != 412:
                raise SnapshotError("store_create_failed") from None
            # Verify the service-validated checksum, not user-controlled metadata.
            try:
                existing = self.client.head_object(**self._args(key), ChecksumMode="ENABLED")
            except Exception:
                raise SnapshotError("store_read_failed") from None
            if (
                existing.get("ChecksumSHA256") != checksum
                or existing["ContentLength"] != path.stat().st_size
            ):
                raise SnapshotError("immutable_object_conflict") from None

    def replace_current(self, data: bytes, *, expected: str | None) -> None:
        condition = {"IfNoneMatch": "*"} if expected is None else {"IfMatch": expected}
        try:
            self.client.put_object(
                **self._args("current.json"),
                **condition,
                Body=data,
                ContentType="application/json",
                CacheControl="no-store",
                ServerSideEncryption="AES256",
                ChecksumSHA256=base64.b64encode(hashlib.sha256(data).digest()).decode("ascii"),
            )
        except Exception as error:
            code = (
                "current_pointer_conflict"
                if self._status(error) in {409, 412}
                else "store_pointer_write_failed"
            )
            # A lost response is ambiguous. Never retry without rereading current.
            raise SnapshotError(code) from None


def put_blob(store: Store, layer: str, path: Path) -> dict[str, Any]:
    if layer not in LAYERS:
        raise SnapshotError("invalid_snapshot_layer")
    _check_file(path)
    digest = file_digest(path)
    reference = {"key": f"{layer}/{digest}", "sha256": digest, "bytes": path.stat().st_size}
    store.create(reference["key"], path)
    return reference
