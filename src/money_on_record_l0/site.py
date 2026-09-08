from __future__ import annotations

import hashlib
import json
import re
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .record_browser import render_browser

SITE_SCHEMA_VERSION = 1
MANIFEST_NAME = "site-manifest.json"
MAX_ARCHIVE_FILES = 100
MAX_ARCHIVE_BYTES = 5 * 1024 * 1024
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class SiteBuildError(ValueError):
    """The static-site content or artifact violates its publication contract."""


@dataclass(frozen=True)
class SiteArtifact:
    archive_sha256: str
    files: int
    bytes: int


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise SiteBuildError(f"{label} must be an object with string keys")
    return value


def _exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise SiteBuildError(f"{label} keys differ from the supported schema")


def _create_archive(path: Path, files: dict[str, bytes]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            # Stored entries avoid output drift across runner zlib versions. The site is tiny,
            # and GitHub artifact transport is also configured not to recompress this ZIP.
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(info, data, compress_type=zipfile.ZIP_STORED)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_site(*, content_path: Path, output: Path, archive: Path, checksum: Path) -> SiteArtifact:
    for target, label in (
        (output, "site output"),
        (archive, "site archive"),
        (checksum, "checksum"),
    ):
        if target.exists():
            raise SiteBuildError(f"{label} already exists: {target}")
    try:
        files, snapshots = render_browser(content_path)
    except (ValueError, OSError) as error:
        raise SiteBuildError(str(error)) from error
    manifest = {
        "schema_version": SITE_SCHEMA_VERSION,
        "content_sha256": hashlib.sha256(content_path.read_bytes()).hexdigest(),
        "files": {
            name: {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            for name, data in sorted(files.items())
        },
        "profiles": [],
        "source_snapshots": snapshots,
    }
    files[MANIFEST_NAME] = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    output.mkdir(parents=True)
    for name, data in sorted(files.items()):
        destination = output / PurePosixPath(name)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        destination.chmod(0o644)
    archive_sha256 = _create_archive(archive, files)
    checksum.parent.mkdir(parents=True, exist_ok=True)
    checksum.write_text(f"{archive_sha256}  {archive.name}\n", encoding="utf-8")
    checksum.chmod(0o644)
    return SiteArtifact(
        archive_sha256=archive_sha256,
        files=len(files),
        bytes=sum(len(data) for data in files.values()),
    )


def _safe_archive_name(name: str) -> bool:
    path = PurePosixPath(name)
    return bool(
        name
        and not name.startswith("/")
        and not name.endswith("/")
        and "\\" not in name
        and all(part not in {"", ".", ".."} for part in path.parts)
    )


def verify_site_archive(
    archive_path: Path, *, expected_sha256: str | None = None, output: Path | None = None
) -> SiteArtifact:
    archive_bytes = archive_path.read_bytes()
    archive_sha256 = hashlib.sha256(archive_bytes).hexdigest()
    if expected_sha256 is not None:
        if not _SHA256.fullmatch(expected_sha256):
            raise SiteBuildError("expected archive digest must be lowercase SHA-256")
        if archive_sha256 != expected_sha256:
            raise SiteBuildError("site archive digest does not match the authorized build")

    with zipfile.ZipFile(archive_path) as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if not infos or len(infos) > MAX_ARCHIVE_FILES or len(names) != len(set(names)):
            raise SiteBuildError("site archive has an invalid file count or duplicate path")
        if any(not _safe_archive_name(info.filename) for info in infos):
            raise SiteBuildError("site archive contains an unsafe path")
        if any(stat.S_ISLNK(info.external_attr >> 16) for info in infos):
            raise SiteBuildError("site archive must not contain symbolic links")
        if sum(info.file_size for info in infos) > MAX_ARCHIVE_BYTES:
            raise SiteBuildError("site archive exceeds the maximum uncompressed size")
        if MANIFEST_NAME not in names:
            raise SiteBuildError("site archive is missing its manifest")

        try:
            manifest = _mapping(json.loads(archive.read(MANIFEST_NAME)), "site manifest")
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise SiteBuildError("site artifact manifest is invalid") from error
        _exact_keys(
            manifest,
            {"schema_version", "content_sha256", "files", "profiles", "source_snapshots"},
            "site manifest",
        )
        if manifest["schema_version"] != SITE_SCHEMA_VERSION:
            raise SiteBuildError("site artifact manifest schema is unsupported")
        manifest_files = _mapping(manifest["files"], "site manifest files")
        if set(names) != set(manifest_files) | {MANIFEST_NAME}:
            raise SiteBuildError("site archive paths do not match its manifest")
        for name, expected in manifest_files.items():
            expected_file = _mapping(expected, f"site manifest files.{name}")
            _exact_keys(expected_file, {"bytes", "sha256"}, f"site manifest files.{name}")
            data = archive.read(name)
            if (
                expected_file["bytes"] != len(data)
                or expected_file["sha256"] != hashlib.sha256(data).hexdigest()
            ):
                raise SiteBuildError("site archive content does not match its manifest")

        if output is not None:
            if output.exists():
                raise SiteBuildError(f"verified extraction output already exists: {output}")
            output.mkdir(parents=True)
            for info in infos:
                destination = output / PurePosixPath(info.filename)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(archive.read(info.filename))
                destination.chmod(0o644)

        return SiteArtifact(
            archive_sha256=archive_sha256,
            files=len(infos),
            bytes=sum(info.file_size for info in infos),
        )
