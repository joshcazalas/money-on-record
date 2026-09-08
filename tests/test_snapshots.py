from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from money_on_record_l0 import snapshots
from money_on_record_l0.record_browser import ROOT
from money_on_record_l0.snapshot_store import LocalStore, SnapshotError
from money_on_record_l0.snapshots import (
    encode,
    publish_snapshot,
    read_current,
    restore_snapshot,
    verify_snapshot,
)

CONTENT = ROOT / "site/content.json"
REVISION = "a" * 40


def current_document(store):
    document, _ = read_current(store)
    assert document is not None
    return document


def publish(store, revision=REVISION):
    return publish_snapshot(store, content_path=CONTENT, code_revision=revision)


@pytest.fixture
def published(tmp_path: Path):
    store = LocalStore(tmp_path / "store")
    snapshot_id = publish(store)
    return store, snapshot_id


def test_publish_is_reproducible_and_preserves_acquisition_dates(published, tmp_path: Path) -> None:
    store, snapshot_id = published
    pointer = (store.root / "current.json").read_bytes()
    assert publish(store) == snapshot_id
    assert (store.root / "current.json").read_bytes() == pointer
    other = LocalStore(tmp_path / "second-store")
    assert publish(other) == snapshot_id
    assert snapshot_id.startswith("20260818T174638Z-")
    manifest = verify_snapshot(store, snapshot_id, output=tmp_path / "export")
    assert len(manifest["sources"]) == 6
    assert manifest["raw_storage"] == "external-lineage-only"
    assert len(list((store.root / "site").iterdir())) == 1
    assert not (store.root / "raw").exists()
    index = (tmp_path / "export/index.html").read_text()
    assert "Research beta" in index
    assert "dev-reload" not in index
    assert (tmp_path / "export/_data/campaign-contributions.json").read_bytes() == (
        ROOT / "site/data/campaign-contributions.json"
    ).read_bytes()
    assert (store.root / manifest["archive"]["key"]).is_file()


def test_restore_changes_only_pointer_and_prevents_aba(published, monkeypatch) -> None:
    store, first = published
    _, original = read_current(store)
    assert original is not None
    second = publish(store, "b" * 40)
    files = {
        path: path.read_bytes()
        for path in store.root.rglob("*")
        if path.is_file() and path.name not in {"current.json", "store.lock"}
    }
    # Recovery reads the immutable archive; it must never rebuild old data.
    monkeypatch.setattr(snapshots, "build_site", lambda **kwargs: pytest.fail("rebuild on restore"))
    monkeypatch.setattr(
        snapshots, "load_inventory", lambda: pytest.fail("live registry on restore")
    )
    restore_snapshot(store, first, expected_current=second)
    assert current_document(store)["snapshot_id"] == first
    assert all(path.read_bytes() == content for path, content in files.items())
    with pytest.raises(SnapshotError, match="current_pointer_conflict"):
        store.replace_current(b"stale writer", expected=original.revision)
    with pytest.raises(SnapshotError, match="current_pointer_conflict"):
        restore_snapshot(store, second, expected_current=second)


@pytest.mark.parametrize("failure", ["site", "snapshots", "pointer"])
def test_failed_storage_does_not_advance_current(published, failure: str) -> None:
    store, first = published
    previous = (store.root / "current.json").read_bytes()

    class FailedStore(LocalStore):
        def create(self, key, path):
            if key.startswith(failure + "/"):
                raise OSError("private source value test@example.com")
            return super().create(key, path)

        def replace_current(self, data, *, expected):
            if failure == "pointer":
                raise OSError("private source value test@example.com")
            return super().replace_current(data, expected=expected)

    with pytest.raises(SnapshotError, match="snapshot_publication_failed"):
        publish(FailedStore(store.root), "b" * 40)
    assert (store.root / "current.json").read_bytes() == previous
    assert current_document(store)["snapshot_id"] == first
    reports = list((store.root / "runs").glob("*/failure.json"))
    assert len(reports) == 1
    report = reports[0].read_text()
    assert "test@example.com" not in report and "private source" not in report
    assert (
        json.loads(report)["phase"]
        == {"site": "store_archive", "snapshots": "store_manifest", "pointer": "advance_current"}[
            failure
        ]
    )


def test_lost_commit_response_reports_uncertainty_and_leaves_valid_snapshot(published) -> None:
    store, _ = published

    class LostResponse(LocalStore):
        def replace_current(self, data, *, expected):
            super().replace_current(data, expected=expected)
            raise SnapshotError("store_pointer_write_failed")

    with pytest.raises(SnapshotError, match="store_pointer_write_failed"):
        publish(LostResponse(store.root), "b" * 40)
    current = current_document(store)
    assert verify_snapshot(store, current["snapshot_id"])["code_revision"] == "b" * 40
    report = json.loads(next((store.root / "runs").glob("*/failure.json")).read_bytes())
    assert report["publication_status"] == "indeterminate"


def test_concurrent_publisher_cannot_overwrite_new_current(published) -> None:
    store, first = published

    class ConcurrentStore(LocalStore):
        def create(self, key, path):
            super().create(key, path)
            if key.startswith("snapshots/"):
                current, revision = read_current(self)
                assert current is not None and revision is not None
                current["generation"] = "f" * 32
                self.replace_current(encode(current), expected=revision.revision)

    with pytest.raises(SnapshotError, match="current_pointer_conflict"):
        publish(ConcurrentStore(store.root), "b" * 40)
    assert current_document(store)["snapshot_id"] == first
    assert current_document(store)["generation"] == "f" * 32


@pytest.mark.parametrize("corruption", ["manifest", "archive", "missing"])
def test_corrupt_or_missing_snapshot_cannot_be_restored(published, corruption: str) -> None:
    store, first = published
    original = verify_snapshot(store, first)
    second = publish(store, "b" * 40)
    before = (store.root / "current.json").read_bytes()
    path = store.root / (
        f"snapshots/{first}.json" if corruption == "manifest" else original["archive"]["key"]
    )
    if corruption == "missing":
        path.unlink()
    else:
        path.write_bytes(b"damaged")
    with pytest.raises(SnapshotError):
        restore_snapshot(store, first, expected_current=second)
    assert (store.root / "current.json").read_bytes() == before


def test_hash_valid_manifest_with_inconsistent_lineage_is_rejected(published) -> None:
    store, snapshot_id = published
    manifest = verify_snapshot(store, snapshot_id)
    manifest["sources"][0]["raw"]["sha256"] = "0" * 64
    data = encode(manifest)
    forged = snapshot_id.split("-", 1)[0] + "-" + hashlib.sha256(data).hexdigest()
    (store.root / f"snapshots/{forged}.json").write_bytes(data)
    with pytest.raises(SnapshotError, match="snapshot_lineage_mismatch"):
        verify_snapshot(store, forged)


@pytest.mark.parametrize("defect", ["checksum", "privacy", "schema", "amount"])
def test_invalid_public_input_is_quarantined_before_any_publication(published, tmp_path, defect):
    store, _ = published
    before = (store.root / "current.json").read_bytes()
    content_dir = tmp_path / "content"
    shutil.copytree(ROOT / "site", content_dir)
    path = content_dir / "data/campaign-contributions.json"
    document = json.loads(path.read_bytes())
    if defect == "privacy":
        document["rows"][0]["donor"] = "private@example.com"
    elif defect == "schema":
        document["rows"][0]["street_address"] = "PRIVATE VALUE"
    elif defect == "amount":
        document["rows"][0]["contribution_amount"] = "NaN"
    else:
        document["rows"].pop()
    path.write_bytes(encode(document))
    if defect != "checksum":
        content_path = content_dir / "content.json"
        content = json.loads(content_path.read_bytes())
        content["publications"]["campaign-contributions"] = hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        content_path.write_bytes(encode(content))
    with pytest.raises(SnapshotError):
        publish_snapshot(store, content_path=content_dir / "content.json", code_revision=REVISION)
    assert (store.root / "current.json").read_bytes() == before
    assert len(list((store.root / "snapshots").iterdir())) == 1
    report = next((store.root / "runs").glob("*/failure.json")).read_text()
    assert "private@example.com" not in report and "PRIVATE VALUE" not in report


def test_cli_fails_nonzero_without_echoing_sdk_or_source_errors(tmp_path):
    path = tmp_path / "current.json"
    path.write_bytes(b"private@example.com invalid json")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "money_on_record_l0.snapshot_cli",
            "--store",
            str(tmp_path),
            "current",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert not result.stdout
    assert json.loads(result.stderr) == {"status": "failed", "code": "invalid_snapshot_json"}


def test_nondeterministic_build_is_rejected_before_storage(published, monkeypatch) -> None:
    from dataclasses import replace

    store, _ = published
    previous = (store.root / "current.json").read_bytes()
    real_build = snapshots.build_site
    calls = 0

    def nondeterministic(**kwargs):
        nonlocal calls
        calls += 1
        artifact = real_build(**kwargs)
        return replace(artifact, archive_sha256="0" * 64) if calls == 2 else artifact

    monkeypatch.setattr(snapshots, "build_site", nondeterministic)
    with pytest.raises(SnapshotError, match="nondeterministic_build"):
        publish(store)
    assert (store.root / "current.json").read_bytes() == previous
    assert len(list((store.root / "snapshots").iterdir())) == 1
