import hashlib
import json

import pytest

from money_on_record_l0.acquire import AcquisitionError, verify_artifacts


def _write_artifact_and_manifest(root, content: bytes) -> None:
    artifact = root / "data" / "raw" / "test-id" / "artifact.csv"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(content)
    manifests = root / "data" / "manifests"
    manifests.mkdir(parents=True)
    payload = {
        "artifact": str(artifact.relative_to(root)),
        "receipt": {
            "sha256": hashlib.sha256(content).hexdigest(),
            "bytes": len(content),
        },
    }
    (manifests / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")


def test_verify_artifacts_checks_hash_and_byte_count(tmp_path) -> None:
    _write_artifact_and_manifest(tmp_path, b"a,b\n1,2\n")

    assert verify_artifacts(tmp_path) == 1


def test_verify_artifacts_rejects_mutated_content(tmp_path) -> None:
    _write_artifact_and_manifest(tmp_path, b"a,b\n1,2\n")
    artifact = tmp_path / "data" / "raw" / "test-id" / "artifact.csv"
    artifact.write_bytes(b"a,b\nchanged,2\n")

    with pytest.raises(AcquisitionError, match="integrity mismatch"):
        verify_artifacts(tmp_path)
