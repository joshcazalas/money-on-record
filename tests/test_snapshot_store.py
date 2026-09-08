from __future__ import annotations

import base64
import hashlib
import io
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import boto3
import pytest
from botocore.response import StreamingBody
from botocore.stub import ANY, Stubber

from money_on_record_l0.snapshot_store import (
    LocalStore,
    S3Store,
    SnapshotError,
    put_blob,
)


def _race(root: str, value: int) -> str:
    try:
        LocalStore(Path(root)).replace_current(str(value).encode(), expected=None)
        return "published"
    except SnapshotError as error:
        return error.code


def test_local_pointer_compare_and_swap_across_processes(tmp_path: Path) -> None:
    with ProcessPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(_race, [str(tmp_path)] * 16, range(16)))
    assert results.count("published") == 1
    assert results.count("current_pointer_conflict") == 15
    current = LocalStore(tmp_path).read("current.json", limit=4096)
    assert current is not None and int(current.data) in range(16)


def test_immutable_layers_deduplicate_and_detect_conflict(tmp_path: Path) -> None:
    store = LocalStore(tmp_path / "store")
    path = tmp_path / "source.csv"
    path.write_bytes(b"PRIVATE SOURCE DATA\n")
    reference = put_blob(store, "raw", path)
    assert reference == put_blob(store, "raw", path)
    assert len(list((store.root / "raw").iterdir())) == 1
    assert (store.root / reference["key"]).stat().st_mode & 0o777 == 0o600
    store.create("snapshots/fixed.json", path)
    path.write_bytes(b"different")
    with pytest.raises(SnapshotError, match="immutable_object_conflict"):
        store.create("snapshots/fixed.json", path)
    with pytest.raises(SnapshotError, match="conditional_pointer_write_required"):
        store.create("current.json", path)
    with pytest.raises(SnapshotError, match="invalid_snapshot_layer"):
        put_blob(store, "public", path)


@pytest.mark.parametrize(
    "key", ["/outside", "../outside", "raw/../../outside", "raw//x", "raw/./x"]
)
def test_store_rejects_unsafe_keys(tmp_path: Path, key: str) -> None:
    with pytest.raises(SnapshotError, match="invalid_object_key"):
        LocalStore(tmp_path).read(key, limit=100)


def test_local_store_rejects_symlink_and_bounded_read(tmp_path: Path) -> None:
    store = LocalStore(tmp_path / "store")
    private = tmp_path / "private"
    private.write_bytes(b"sensitive contents")
    (store.root / "raw").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(SnapshotError, match="unsafe_store_path"):
        store.read("raw/private", limit=100)
    store.replace_current(b"too long", expected=None)
    with pytest.raises(SnapshotError, match="object_too_large"):
        store.read("current.json", limit=3)


@pytest.fixture
def s3():
    client = boto3.client(
        "s3", region_name="us-east-1", aws_access_key_id="test", aws_secret_access_key="test"
    )
    store = S3Store(
        bucket="test-snapshot-bucket", account_id="123456789012", prefix="uat", client=client
    )
    with Stubber(client) as stub:
        yield store, stub
        stub.assert_no_pending_responses()


def _s3_args(key: str) -> dict:
    return {
        "Bucket": "test-snapshot-bucket",
        "Key": f"uat/{key}",
        "ExpectedBucketOwner": "123456789012",
    }


def test_s3_read_uses_opaque_etag_and_checks_owner(s3) -> None:
    store, stub = s3
    data = b'{"snapshot":"one"}'
    stub.add_response(
        "get_object",
        {
            "Body": StreamingBody(io.BytesIO(data), len(data)),
            "ContentLength": len(data),
            "ETag": '"opaque-etag"',
        },
        _s3_args("current.json"),
    )
    result = store.read("current.json", limit=4096)
    assert result.data == data and result.revision == '"opaque-etag"'


@pytest.mark.parametrize("expected", [None, '"previous-etag"'])
def test_s3_pointer_writes_use_service_preconditions(s3, expected: str | None) -> None:
    store, stub = s3
    data = b"new pointer"
    stub.add_response(
        "put_object",
        {},
        {
            **_s3_args("current.json"),
            **({"IfNoneMatch": "*"} if expected is None else {"IfMatch": expected}),
            "Body": data,
            "ContentType": "application/json",
            "CacheControl": "no-store",
            "ServerSideEncryption": "AES256",
            "ChecksumSHA256": base64.b64encode(hashlib.sha256(data).digest()).decode(),
        },
    )
    store.replace_current(data, expected=expected)


@pytest.mark.parametrize("status", [409, 412, 403, 503])
def test_s3_pointer_failure_is_sanitized_and_not_blindly_retried(s3, status: int) -> None:
    store, stub = s3
    stub.add_client_error(
        "put_object",
        service_error_code="Failure",
        service_message="private-token@example.com",
        http_status_code=status,
    )
    with pytest.raises(SnapshotError) as error:
        store.replace_current(b"pointer", expected='"old"')
    assert error.value.code == (
        "current_pointer_conflict" if status in {409, 412} else "store_pointer_write_failed"
    )
    assert "private-token" not in str(error.value)


def test_s3_immutable_create_deduplicates_only_matching_service_checksum(
    s3, tmp_path: Path
) -> None:
    store, stub = s3
    path = tmp_path / "data"
    path.write_bytes(b"snapshot")
    checksum = base64.b64encode(hashlib.sha256(b"snapshot").digest()).decode()
    stub.add_client_error(
        "put_object",
        service_error_code="PreconditionFailed",
        http_status_code=412,
        expected_params={
            **_s3_args("site/hash"),
            "Body": ANY,
            "ContentLength": 8,
            "ChecksumSHA256": checksum,
            "IfNoneMatch": "*",
            "ServerSideEncryption": "AES256",
        },
    )
    stub.add_response(
        "head_object",
        {"ContentLength": 8, "ChecksumSHA256": checksum},
        {**_s3_args("site/hash"), "ChecksumMode": "ENABLED"},
    )
    store.create("site/hash", path)
    stub.add_client_error(
        "put_object", service_error_code="PreconditionFailed", http_status_code=412
    )
    stub.add_response(
        "head_object",
        {"ContentLength": 8, "ChecksumSHA256": "different"},
        {**_s3_args("site/hash"), "ChecksumMode": "ENABLED"},
    )
    with pytest.raises(SnapshotError, match="immutable_object_conflict"):
        store.create("site/hash", path)


def test_s3_partial_read_and_permission_denied_are_not_missing_objects(s3) -> None:
    store, stub = s3
    stub.add_response(
        "get_object",
        {"ContentLength": 99, "ETag": '"x"', "Body": StreamingBody(io.BytesIO(b"short"), 5)},
        _s3_args("raw/x"),
    )
    with pytest.raises(SnapshotError, match="object_size_mismatch"):
        store.read("raw/x", limit=100)
    stub.add_client_error("get_object", service_error_code="AccessDenied", http_status_code=403)
    with pytest.raises(SnapshotError, match="store_read_failed"):
        store.read("current.json", limit=4096)
    stub.add_client_error("get_object", service_error_code="NoSuchKey", http_status_code=404)
    assert store.read("current.json", limit=4096) is None


def test_interrupted_local_pointer_write_keeps_previous_bytes(tmp_path, monkeypatch) -> None:
    import os

    store = LocalStore(tmp_path)
    store.replace_current(b"previous", expected=None)
    previous = store.read("current.json", limit=100)
    assert previous is not None

    def interrupted(*args):
        raise OSError("interrupted before rename")

    monkeypatch.setattr(os, "replace", interrupted)
    with pytest.raises(OSError):
        store.replace_current(b"partial publication", expected=previous.revision)
    assert store.read("current.json", limit=100) == previous
    assert {path.name for path in tmp_path.iterdir()} == {"current.json", "store.lock"}


def test_content_addressed_upload_rejects_changed_source(tmp_path) -> None:
    store = LocalStore(tmp_path / "store")
    path = tmp_path / "source"
    path.write_bytes(b"changed bytes")
    key = "raw/" + hashlib.sha256(b"original bytes").hexdigest()
    with pytest.raises(SnapshotError, match="source_changed_during_upload"):
        store.create(key, path)
    assert not (store.root / key).exists()
