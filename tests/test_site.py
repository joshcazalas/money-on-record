from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from html.parser import HTMLParser
from pathlib import Path

import pytest

from money_on_record_l0.site import (
    MANIFEST_NAME,
    SiteBuildError,
    build_site,
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


def _build(tmp_path: Path, suffix: str = "one") -> tuple[Path, Path, Path]:
    output = tmp_path / f"site-{suffix}"
    archive = tmp_path / f"site-{suffix}.zip"
    checksum = tmp_path / f"site-{suffix}.zip.sha256"
    build_site(content_path=CONTENT, output=output, archive=archive, checksum=checksum)
    return output, archive, checksum


def test_site_build_contains_the_browser_and_only_its_public_inputs(tmp_path: Path) -> None:
    output, archive, checksum = _build(tmp_path)
    index = (output / "index.html").read_text()
    assert "Campaign contributions" in index
    assert "Research beta" in index
    assert "Local preview" not in index
    assert "dev-reload" not in index
    assert "Follow the records" not in index
    assert "Page not found" in (output / "404.html").read_text()
    legacy = (output / "profiles/austin-board-of-realtors/index.html").read_text()
    assert "unverified" in legacy
    assert "contributions?q=Austin+Board+of+REALTORS" in legacy
    assert 'href="/#/payments"' in legacy
    assert (output / "robots.txt").read_text() == "User-agent: *\nDisallow: /\n"
    assert checksum.read_text().split()[0] == verify_site_archive(archive).archive_sha256
    assert len(list((output / "assets").iterdir())) == 4
    assert len(list((output / "_data").iterdir())) == 3
    assert len([p for p in output.rglob("*") if p.is_file()]) == 12
    logic = next((output / "assets").glob("data-*.js"))
    app = next((output / "assets").glob("app-*.js"))
    assert f'"/assets/{logic.name}"' in app.read_text()
    public_bytes = b"".join(p.read_bytes() for p in output.rglob("*") if p.is_file())
    for prohibited in (b"donor_address", b"contract_contact_email_ad", b"vendor_address"):
        assert prohibited not in public_bytes


def test_html_pages_have_accessible_fallbacks_and_privacy_controls(tmp_path: Path) -> None:
    output, _archive, _checksum = _build(tmp_path)
    for page in sorted(output.rglob("*.html")):
        text = page.read_text()
        audit = PageAudit()
        audit.feed(text)
        assert audit.html_lang == "en"
        assert audit.has_viewport and audit.has_title
        assert audit.h1_count == 1
        assert len(audit.ids) == len(set(audit.ids))
        assert "content" in audit.ids
        for attributes, label in audit.links:
            assert attributes.get("href")
            assert label or attributes.get("aria-label")
            if attributes["href"].startswith("https://"):
                assert "noreferrer" in attributes.get("rel", "")
        assert 'name="robots" content="noindex,nofollow,noarchive"' in text
        assert "script-src 'self'" in text
        assert "connect-src 'self'" in text
        assert 'name="referrer" content="no-referrer"' in text
        assert 'class="skip-link"' in text


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
    assert manifest["profiles"] == []
    assert len(manifest["source_snapshots"]) == 6


def test_site_archive_rejects_wrong_digest_and_unsafe_paths(tmp_path: Path) -> None:
    _output, archive, _checksum = _build(tmp_path)
    with pytest.raises(SiteBuildError, match="does not match"):
        verify_site_archive(archive, expected_sha256="0" * 64)

    unsafe = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(unsafe, "w") as value:
        value.writestr("../index.html", "unsafe")
    with pytest.raises(SiteBuildError, match="unsafe path"):
        verify_site_archive(unsafe)


def _content_copy(tmp_path: Path) -> Path:
    shutil.copytree(CONTENT.parent, tmp_path / "input")
    return tmp_path / "input/content.json"


def _change_publication(content: Path, slug: str, mutate) -> None:
    path = content.parent / "data" / f"{slug}.json"
    document = json.loads(path.read_text())
    mutate(document)
    path.write_text(json.dumps(document))
    manifest = json.loads(content.read_text())
    manifest["publications"][slug] = hashlib.sha256(path.read_bytes()).hexdigest()
    content.write_text(json.dumps(manifest))


def _build_content(content: Path, tmp_path: Path) -> None:
    build_site(
        content_path=content,
        output=tmp_path / "out",
        archive=tmp_path / "out.zip",
        checksum=tmp_path / "out.sha256",
    )


def test_publication_rejects_unreviewed_edits(tmp_path: Path) -> None:
    content = _content_copy(tmp_path)
    path = content.parent / "data/campaign-contributions.json"
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(SiteBuildError, match="checksum"):
        _build_content(content, tmp_path)


@pytest.mark.parametrize(
    "field,value,message",
    [
        ("donor", "Contact someone@example.org", "privacy scan"),
        ("donor_type", "INDIVIDUAL", "selected coverage"),
        ("contribution_amount", "NaN", "Invalid record"),
        ("contribution_amount", "10.001", "Invalid record"),
        ("contribution_date", "not a date", "Invalid record"),
        ("donor_address", "restricted", "Unexpected record fields"),
    ],
)
def test_publication_revalidates_rows_even_when_digest_is_updated(
    tmp_path: Path, field: str, value: str, message: str
) -> None:
    content = _content_copy(tmp_path)
    _change_publication(
        content, "campaign-contributions", lambda d: d["rows"][0].update({field: value})
    )
    with pytest.raises(SiteBuildError, match=message):
        _build_content(content, tmp_path)


def test_publication_rejects_unknown_fields_in_declared_schema(tmp_path: Path) -> None:
    content = _content_copy(tmp_path)
    _change_publication(content, "echeckbook", lambda d: d["fields"].append("contact_email"))
    with pytest.raises(SiteBuildError, match="not allowlisted"):
        _build_content(content, tmp_path)


def test_publication_rejects_duplicate_ids_and_false_source_lineage(tmp_path: Path) -> None:
    content = _content_copy(tmp_path)
    _change_publication(content, "campaign-contributions", lambda d: d["rows"].append(d["rows"][0]))
    with pytest.raises(SiteBuildError, match="unique"):
        _build_content(content, tmp_path)
    _change_publication(content, "campaign-contributions", lambda d: d.update({"sha256": "0" * 64}))
    with pytest.raises(SiteBuildError, match="lineage"):
        _build_content(content, tmp_path)


def test_source_directory_must_match_frozen_profiles(tmp_path: Path) -> None:
    content = _content_copy(tmp_path)
    _change_publication(content, "sources", lambda d: d[0].update({"row_count": 1}))
    with pytest.raises(SiteBuildError, match="Source directory differs"):
        _build_content(content, tmp_path)
