from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import pytest

from money_on_record_l0.site import (
    MANIFEST_NAME,
    SiteBuildError,
    build_site,
    load_site_content,
    verify_site_archive,
)

ROOT = Path(__file__).resolve().parents[1]
CONTENT = ROOT / "site" / "content.json"


class PageAudit(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.html_lang = ""
        self.has_viewport = False
        self.has_title = False
        self.in_title = False
        self.h1_count = 0
        self.ids: list[str] = []
        self.links: list[tuple[dict[str, str], str]] = []
        self._link_attributes: dict[str, str] | None = None
        self._link_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {name: value or "" for name, value in attrs}
        if tag == "html":
            self.html_lang = attributes.get("lang", "")
        if tag == "meta" and attributes.get("name") == "viewport":
            self.has_viewport = bool(attributes.get("content"))
        if tag == "title":
            self.in_title = True
        if tag == "h1":
            self.h1_count += 1
        if identifier := attributes.get("id"):
            self.ids.append(identifier)
        if tag == "a":
            self._link_attributes = attributes
            self._link_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self.in_title = False
        if tag == "a" and self._link_attributes is not None:
            self.links.append((self._link_attributes, "".join(self._link_text).strip()))
            self._link_attributes = None
            self._link_text = []

    def handle_data(self, data: str) -> None:
        if self.in_title and data.strip():
            self.has_title = True
        if self._link_attributes is not None:
            self._link_text.append(data)


def _build(tmp_path: Path, suffix: str = "one", content: Path = CONTENT) -> tuple[Path, Path, Path]:
    output = tmp_path / f"site-{suffix}"
    archive = tmp_path / f"site-{suffix}.zip"
    checksum = tmp_path / f"site-{suffix}.zip.sha256"
    build_site(content_path=content, output=output, archive=archive, checksum=checksum)
    return output, archive, checksum


def _content_copy(tmp_path: Path) -> tuple[dict[str, Any], Path]:
    directory = tmp_path / "content"
    directory.mkdir()
    shutil.copytree(ROOT / "site" / "data", directory / "data")
    document = json.loads(CONTENT.read_text(encoding="utf-8"))
    return document, directory / "content.json"


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def test_site_build_is_a_reporter_oriented_record_explorer(tmp_path: Path) -> None:
    output, archive, checksum = _build(tmp_path)

    index = (output / "index.html").read_text(encoding="utf-8")
    profile = (output / "profiles" / "austin-board-of-realtors" / "index.html").read_text(
        encoding="utf-8"
    )
    not_found = (output / "404.html").read_text(encoding="utf-8")

    assert "Austin campaign contributions and City payments" in index
    assert "Follow the records" not in index
    assert "Keep the caveats" not in index
    assert 'href="/profiles/austin-board-of-realtors/index.html"' in index
    assert "Do not treat this as a confirmed identity" in profile
    assert "$240,133.82" in profile
    assert "$106,072.10" in profile
    assert "Payments by department" in profile
    assert "Austin Energy" in profile
    assert "$86,195.00" in profile
    assert "Advertising/publication" in profile
    assert "no line-item descriptions" in profile
    assert profile.count("data-record-row") == 261
    assert "Filter contributions" in profile
    assert "Filter payment lines" in profile
    assert "Download these 53 projected official rows as CSV" in profile
    assert "Download these 208 projected official rows as CSV" in profile
    assert "services.austintexas.gov/edims/document.cfm" in profile
    assert "There is no profile at this address" in not_found
    assert (output / "robots.txt").read_text(encoding="utf-8") == "User-agent: *\nDisallow: /\n"
    assert (
        checksum.read_text(encoding="utf-8").split()[0]
        == verify_site_archive(archive).archive_sha256
    )

    public_files = {
        path.relative_to(output).as_posix() for path in output.rglob("*") if path.is_file()
    }
    assert {
        path for path in public_files if path.startswith("assets/site-") and path.endswith(".css")
    }
    assert {
        path for path in public_files if path.startswith("assets/site-") and path.endswith(".js")
    }
    assert "site-manifest.json" in public_files
    assert not any(path.startswith("data/") for path in public_files)

    public_bytes = b"".join(
        path.read_bytes() for path in sorted(output.rglob("*")) if path.is_file()
    )
    for prohibited in (
        b"donor_address",
        b"contract_contact_email_ad",
        b"vendor_address",
        b"Not for publication",
    ):
        assert prohibited not in public_bytes


def test_every_html_page_has_accessibility_and_privacy_controls(tmp_path: Path) -> None:
    output, _archive, _checksum = _build(tmp_path)

    for page in sorted(output.rglob("*.html")):
        audit = PageAudit()
        source = page.read_text(encoding="utf-8")
        audit.feed(source)

        assert audit.html_lang == "en", page
        assert audit.has_viewport, page
        assert audit.has_title, page
        assert audit.h1_count == 1, page
        assert len(audit.ids) == len(set(audit.ids)), page
        assert "content" in audit.ids, page
        assert audit.links, page
        for attributes, text in audit.links:
            assert attributes.get("href"), (page, attributes)
            assert text or attributes.get("aria-label"), (page, attributes)
            if attributes["href"].startswith("https://"):
                assert attributes.get("referrerpolicy") == "no-referrer"
                assert "noopener" in attributes.get("rel", "")

        assert 'href="#content">Skip to content</a>' in source
        assert 'name="robots" content="noindex,nofollow,noarchive"' in source
        assert "default-src 'none'" in source
        assert "script-src 'self'" in source
        assert 'name="referrer" content="no-referrer"' in source

    css = next((output / "assets").glob("site-*.css")).read_text(encoding="utf-8")
    javascript = next((output / "assets").glob("site-*.js")).read_text(encoding="utf-8")
    assert "@media (max-width: 760px)" in css
    assert "@media (prefers-reduced-motion: reduce)" in css
    assert "data-record-filter" in javascript
    assert "data-record-sort" in javascript


def test_site_archive_is_byte_for_byte_reproducible(tmp_path: Path) -> None:
    _output_one, archive_one, checksum_one = _build(tmp_path, "one")
    _output_two, archive_two, checksum_two = _build(tmp_path, "two")

    assert archive_one.read_bytes() == archive_two.read_bytes()
    assert (
        checksum_one.read_text(encoding="utf-8").split()[0]
        == checksum_two.read_text(encoding="utf-8").split()[0]
    )


def test_site_archive_verifies_manifest_and_extracts_safely(tmp_path: Path) -> None:
    output, archive, checksum = _build(tmp_path)
    expected = checksum.read_text(encoding="utf-8").split()[0]
    extracted = tmp_path / "verified"

    result = verify_site_archive(archive, expected_sha256=expected, output=extracted)

    assert result.files == len([path for path in output.rglob("*") if path.is_file()])
    assert (extracted / "index.html").read_bytes() == (output / "index.html").read_bytes()
    manifest = json.loads((extracted / MANIFEST_NAME).read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 2
    assert manifest["profiles"] == ["austin-board-of-realtors"]
    assert len(manifest["source_snapshots"]) == 2


def test_site_archive_rejects_wrong_digest_and_unsafe_paths(tmp_path: Path) -> None:
    _output, archive, _checksum = _build(tmp_path)
    with pytest.raises(SiteBuildError, match="does not match"):
        verify_site_archive(archive, expected_sha256="0" * 64)

    unsafe = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(unsafe, "w") as value:
        value.writestr("../index.html", "unsafe")
    with pytest.raises(SiteBuildError, match="unsafe path"):
        verify_site_archive(unsafe)


def test_site_content_rejects_broad_links_sensitive_text_and_wrong_totals(tmp_path: Path) -> None:
    document, content_path = _content_copy(tmp_path)
    document["profiles"][0]["summary"] = "Contact research@example.org for details."
    _write_json(content_path, document)
    with pytest.raises(SiteBuildError, match="prohibited contact"):
        load_site_content(content_path)

    document = json.loads(CONTENT.read_text(encoding="utf-8"))
    document["profiles"][0]["metrics"][0]["official_rows_url"] = (
        "https://data.austintexas.gov/resource/3kfv-biw6.json?$where=donor%3Dtest"
    )
    _write_json(content_path, document)
    with pytest.raises(SiteBuildError, match="only \\$select"):
        load_site_content(content_path)

    document = json.loads(CONTENT.read_text(encoding="utf-8"))
    metric = document["profiles"][0]["metrics"][0]
    metric["official_rows_url"] = metric["official_rows_url"].replace(
        "transaction_id%2C", "donor_address%2C"
    )
    _write_json(content_path, document)
    with pytest.raises(SiteBuildError, match="prohibited public fields"):
        load_site_content(content_path)

    document = json.loads(CONTENT.read_text(encoding="utf-8"))
    document["profiles"][0]["metrics"][0]["amount_cents"] += 1
    _write_json(content_path, document)
    with pytest.raises(SiteBuildError, match="does not match its records"):
        load_site_content(content_path)

    document = json.loads(CONTENT.read_text(encoding="utf-8"))
    document["profiles"][0]["metrics"][0]["records_sha256"] = "0" * 64
    _write_json(content_path, document)
    with pytest.raises(SiteBuildError, match="does not match records_sha256"):
        load_site_content(content_path)


def test_record_projection_rejects_sensitive_text(tmp_path: Path) -> None:
    document, content_path = _content_copy(tmp_path)
    records_path = content_path.parent / "data" / "austin-board-of-realtors-campaign.json"
    records = json.loads(records_path.read_text(encoding="utf-8"))
    records["records"][0]["recipient"] = "Contact research@example.org"
    _write_json(records_path, records)
    metric = document["profiles"][0]["metrics"][0]
    metric["records_sha256"] = hashlib.sha256(records_path.read_bytes()).hexdigest()
    _write_json(content_path, document)

    with pytest.raises(SiteBuildError, match="prohibited contact"):
        load_site_content(content_path)


def test_site_content_rejects_an_empty_profile_set(tmp_path: Path) -> None:
    document = json.loads(CONTENT.read_text(encoding="utf-8"))
    document["profiles"] = []
    empty_content = tmp_path / "empty-content.json"
    _write_json(empty_content, document)

    with pytest.raises(SiteBuildError, match="non-empty list"):
        load_site_content(empty_content)


def test_generated_html_escapes_hostile_source_text(tmp_path: Path) -> None:
    document, content_path = _content_copy(tmp_path)
    document["profiles"][0]["name"] = "Example <script>alert(1)</script>"
    _write_json(content_path, document)
    output, _archive, _checksum = _build(tmp_path, "hostile", content_path)
    profile = (output / "profiles" / "austin-board-of-realtors" / "index.html").read_text(
        encoding="utf-8"
    )

    assert "<script>alert(1)</script>" not in profile
    assert "Example &lt;script&gt;alert(1)&lt;/script&gt;" in profile
