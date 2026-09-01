# ruff: noqa: E501
from __future__ import annotations

import hashlib
import html
import json
import re
import stat
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

from .privacy import contains_pii

SITE_SCHEMA_VERSION = 1
CONTENT_SCHEMA_VERSION = 2
RECORD_SCHEMA_VERSION = 1
MANIFEST_NAME = "site-manifest.json"
MAX_ARCHIVE_FILES = 100
MAX_ARCHIVE_BYTES = 5 * 1024 * 1024
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_PROHIBITED_PUBLIC_FIELDS = (
    "ad_ln_1",
    "ad_ln_2",
    "contract_contact_email_ad",
    "contract_contact_nm",
    "contract_contact_voice_ph_no",
    "city_state_zip",
    "donor_address",
    "donor_reported_employer",
    "donor_reported_occupation",
    "filer_address_2",
    "filer_phone",
    "guarantor_address_2",
    "guarantor_employer",
    "guarantor_name",
    "guarantor_occupation",
    "transactor_address_2",
    "transactor_employer",
    "transactor_occupation",
    "treasurer_address_2",
    "treasurer_name",
    "treasurer_phone",
)
_PROHIBITED_PUBLIC_FIELD_PATTERNS = (
    "ad_ln",
    "address",
    "city",
    "contact",
    "email",
    "employer",
    "occupation",
    "phone",
    "telephone",
    "zip",
)
_EXTERNAL_LINK_ATTRIBUTES = 'referrerpolicy="no-referrer" rel="external noopener"'


class SiteBuildError(ValueError):
    """The static-site content or artifact violates its publication contract."""


@dataclass(frozen=True)
class CampaignRecord:
    amount_cents: int
    date: str
    recipient: str
    report_url: str
    transaction_id: str
    type: str


@dataclass(frozen=True)
class SpendingRecord:
    accounting_line: str
    amount_cents: int
    commodity_line: str
    date: str
    department: str
    document_code: str
    document_department: str
    document_id: str
    object: str
    vendor_line: str


Record = CampaignRecord | SpendingRecord


@dataclass(frozen=True)
class Metric:
    kind: str
    label: str
    amount_cents: int
    row_count: int
    row_description: str
    source_title: str
    dataset_id: str
    dataset_url: str
    official_rows_url: str
    snapshot_sha256: str
    records_file: str
    records_sha256: str
    records: tuple[Record, ...]


@dataclass(frozen=True)
class Identity:
    status: str
    evidence_tier: str
    campaign_name: str
    public_spending_name: str
    explanation: str


@dataclass(frozen=True)
class Profile:
    slug: str
    name: str
    summary: str
    identity: Identity
    metrics: tuple[Metric, ...]
    snapshot_date: str


@dataclass(frozen=True)
class SiteContent:
    beta_notice: str
    profiles: tuple[Profile, ...]
    content_sha256: str


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
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        raise SiteBuildError(f"{label} keys differ (missing={missing}, unexpected={unexpected})")


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SiteBuildError(f"{label} must be a non-empty string")
    if value != value.strip() or any(ord(character) < 32 for character in value):
        raise SiteBuildError(f"{label} contains surrounding whitespace or control characters")
    return value


def _privacy_safe_text(value: object, label: str) -> str:
    text = _text(value, label)
    if contains_pii(text, field=label.replace(".", "_")):
        raise SiteBuildError(f"{label} contains a prohibited contact or address pattern")
    return text


def _positive_int(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise SiteBuildError(f"{label} must be a positive integer")
    return value


def _date_text(value: object, label: str) -> str:
    text = _text(value, label)
    try:
        parsed = date.fromisoformat(text)
    except ValueError as error:
        raise SiteBuildError(f"{label} must be an ISO calendar date") from error
    if parsed.isoformat() != text:
        raise SiteBuildError(f"{label} must be an ISO calendar date")
    return text


def _line_token(value: object, label: str) -> str:
    text = _text(value, label)
    if not re.fullmatch(r"[A-Za-z0-9-]+", text):
        raise SiteBuildError(f"{label} contains an invalid source identifier")
    return text


def _report_url(value: object, label: str) -> str:
    url = _text(value, label)
    parsed = urlparse(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "services.austintexas.gov"
        or parsed.path != "/edims/document.cfm"
        or parsed.fragment
        or set(query) != {"id"}
        or len(query["id"]) != 1
        or not query["id"][0].isdigit()
    ):
        raise SiteBuildError(f"{label} must be an exact official City filing URL")
    return url


def _records_path(content_path: Path, value: object, label: str) -> tuple[str, Path]:
    relative = _text(value, label)
    pure = PurePosixPath(relative)
    if (
        pure.is_absolute()
        or pure.suffix != ".json"
        or not pure.parts
        or pure.parts[0] != "data"
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise SiteBuildError(f"{label} must be a safe JSON path below site/data")
    resolved = (content_path.parent / Path(*pure.parts)).resolve()
    if not resolved.is_relative_to(content_path.parent.resolve()):
        raise SiteBuildError(f"{label} leaves the site content directory")
    return relative, resolved


def _load_records(
    path: Path, *, kind: str, expected_sha256: str, label: str
) -> tuple[tuple[Record, ...], bytes]:
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise SiteBuildError(f"{label} could not be read: {path}") from error
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise SiteBuildError(f"{label} does not match records_sha256")
    try:
        document = _mapping(json.loads(raw), label)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise SiteBuildError(f"{label} is not valid UTF-8 JSON") from error
    _exact_keys(document, {"schema_version", "kind", "records"}, label)
    if document["schema_version"] != RECORD_SCHEMA_VERSION or document["kind"] != kind:
        raise SiteBuildError(f"{label} has the wrong schema version or record kind")
    raw_records = document["records"]
    if not isinstance(raw_records, list) or not raw_records:
        raise SiteBuildError(f"{label}.records must be a non-empty list")

    records: list[Record] = []
    unique_keys: set[tuple[str, ...]] = set()
    for index, value in enumerate(raw_records):
        record_label = f"{label}.records[{index}]"
        record = _mapping(value, record_label)
        if kind == "campaign":
            _exact_keys(
                record,
                {"amount_cents", "date", "recipient", "report_url", "transaction_id", "type"},
                record_label,
            )
            parsed: Record = CampaignRecord(
                amount_cents=_positive_int(record["amount_cents"], f"{record_label}.amount_cents"),
                date=_date_text(record["date"], f"{record_label}.date"),
                recipient=_privacy_safe_text(record["recipient"], f"{record_label}.recipient"),
                report_url=_report_url(record["report_url"], f"{record_label}.report_url"),
                transaction_id=_line_token(
                    record["transaction_id"], f"{record_label}.transaction_id"
                ),
                type=_privacy_safe_text(record["type"], f"{record_label}.type"),
            )
            unique_key = (parsed.transaction_id,)
        else:
            _exact_keys(
                record,
                {
                    "accounting_line",
                    "amount_cents",
                    "commodity_line",
                    "date",
                    "department",
                    "document_code",
                    "document_department",
                    "document_id",
                    "object",
                    "vendor_line",
                },
                record_label,
            )
            parsed = SpendingRecord(
                accounting_line=_line_token(
                    record["accounting_line"], f"{record_label}.accounting_line"
                ),
                amount_cents=_positive_int(record["amount_cents"], f"{record_label}.amount_cents"),
                commodity_line=_line_token(
                    record["commodity_line"], f"{record_label}.commodity_line"
                ),
                date=_date_text(record["date"], f"{record_label}.date"),
                department=_privacy_safe_text(record["department"], f"{record_label}.department"),
                document_code=_line_token(record["document_code"], f"{record_label}.document_code"),
                document_department=_line_token(
                    record["document_department"], f"{record_label}.document_department"
                ),
                document_id=_line_token(record["document_id"], f"{record_label}.document_id"),
                object=_privacy_safe_text(record["object"], f"{record_label}.object"),
                vendor_line=_line_token(record["vendor_line"], f"{record_label}.vendor_line"),
            )
            unique_key = (
                parsed.document_code,
                parsed.document_department,
                parsed.document_id,
                parsed.vendor_line,
                parsed.commodity_line,
                parsed.accounting_line,
            )
        if unique_key in unique_keys:
            raise SiteBuildError(f"{record_label} duplicates a source record identifier")
        unique_keys.add(unique_key)
        records.append(parsed)

    return tuple(records), raw


def _official_url(value: object, dataset_id: str, *, rows: bool, label: str) -> str:
    url = _text(value, label)
    parsed = urlparse(url)
    expected_path = f"/resource/{dataset_id}.json" if rows else f"/d/{dataset_id}"
    if (
        parsed.scheme != "https"
        or parsed.netloc != "data.austintexas.gov"
        or parsed.path != expected_path
        or parsed.fragment
    ):
        raise SiteBuildError(f"{label} must be the exact official Austin dataset URL")
    query = parse_qs(parsed.query, keep_blank_values=True)
    if rows:
        if set(query) != {"$limit", "$select", "$where"}:
            raise SiteBuildError(f"{label} must contain only $select, $where, and $limit")
        if query["$limit"] != ["50000"] or not query["$select"][0] or not query["$where"][0]:
            raise SiteBuildError(f"{label} has an invalid exact-row projection")
        selected_fields = query["$select"][0].split(",")
        if len(selected_fields) != len(set(selected_fields)) or any(
            not re.fullmatch(r"[a-z][a-z0-9_]*", field) for field in selected_fields
        ):
            raise SiteBuildError(f"{label} must select a unique list of source fields")
        where_identifiers = re.findall(
            r"\b[a-z][a-z0-9_]*\b",
            re.sub(r"'(?:''|[^'])*'", "", query["$where"][0].casefold()),
        )
        unsafe_fields = sorted(
            field
            for field in set(selected_fields) | set(where_identifiers)
            if field in _PROHIBITED_PUBLIC_FIELDS
            or any(pattern in field for pattern in _PROHIBITED_PUBLIC_FIELD_PATTERNS)
        )
        if unsafe_fields:
            raise SiteBuildError(f"{label} references prohibited public fields: {unsafe_fields}")
    elif query:
        raise SiteBuildError(f"{label} must not contain a query")
    return url


def load_site_content(path: Path) -> SiteContent:
    raw = path.read_bytes()
    try:
        document = _mapping(json.loads(raw), "site content")
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise SiteBuildError(f"{path} is not valid UTF-8 JSON") from error

    _exact_keys(document, {"schema_version", "beta_notice", "profiles"}, "site content")
    if document["schema_version"] != CONTENT_SCHEMA_VERSION:
        raise SiteBuildError(f"site content schema must be {CONTENT_SCHEMA_VERSION}")
    beta_notice = _privacy_safe_text(document["beta_notice"], "beta_notice")
    raw_profiles = document["profiles"]
    if not isinstance(raw_profiles, list) or not raw_profiles:
        raise SiteBuildError("profiles must be a non-empty list")

    profiles: list[Profile] = []
    record_payloads: dict[str, bytes] = {}
    slugs: set[str] = set()
    for profile_index, raw_profile in enumerate(raw_profiles):
        label = f"profiles[{profile_index}]"
        profile = _mapping(raw_profile, label)
        _exact_keys(
            profile,
            {"slug", "name", "summary", "identity", "metrics", "snapshot_date"},
            label,
        )
        slug = _text(profile["slug"], f"{label}.slug")
        if not _SLUG.fullmatch(slug) or slug in slugs:
            raise SiteBuildError(f"{label}.slug must be unique lowercase kebab-case")
        slugs.add(slug)

        identity_label = f"{label}.identity"
        raw_identity = _mapping(profile["identity"], identity_label)
        _exact_keys(
            raw_identity,
            {
                "status",
                "evidence_tier",
                "campaign_name",
                "public_spending_name",
                "explanation",
            },
            identity_label,
        )
        identity = Identity(
            status=_privacy_safe_text(raw_identity["status"], f"{identity_label}.status"),
            evidence_tier=_privacy_safe_text(
                raw_identity["evidence_tier"], f"{identity_label}.evidence_tier"
            ),
            campaign_name=_privacy_safe_text(
                raw_identity["campaign_name"], f"{identity_label}.campaign_name"
            ),
            public_spending_name=_privacy_safe_text(
                raw_identity["public_spending_name"],
                f"{identity_label}.public_spending_name",
            ),
            explanation=_privacy_safe_text(
                raw_identity["explanation"], f"{identity_label}.explanation"
            ),
        )
        if "unverified" not in identity.status.casefold():
            raise SiteBuildError(f"{identity_label}.status must remain visibly unverified")

        raw_metrics = profile["metrics"]
        if not isinstance(raw_metrics, list) or len(raw_metrics) < 2:
            raise SiteBuildError(f"{label}.metrics must contain at least two source metrics")
        metrics: list[Metric] = []
        metric_kinds: set[str] = set()
        for metric_index, raw_metric in enumerate(raw_metrics):
            metric_label = f"{label}.metrics[{metric_index}]"
            metric = _mapping(raw_metric, metric_label)
            _exact_keys(
                metric,
                {
                    "kind",
                    "label",
                    "amount_cents",
                    "row_count",
                    "row_description",
                    "source_title",
                    "dataset_id",
                    "dataset_url",
                    "official_rows_url",
                    "snapshot_sha256",
                    "records_file",
                    "records_sha256",
                },
                metric_label,
            )
            kind = _text(metric["kind"], f"{metric_label}.kind")
            if kind not in {"campaign", "spending"} or kind in metric_kinds:
                raise SiteBuildError(f"{metric_label}.kind must be unique campaign or spending")
            metric_kinds.add(kind)
            dataset_id = _text(metric["dataset_id"], f"{metric_label}.dataset_id")
            if not re.fullmatch(r"[a-z0-9]{4}-[a-z0-9]{4}", dataset_id):
                raise SiteBuildError(f"{metric_label}.dataset_id is invalid")
            snapshot_sha256 = _text(metric["snapshot_sha256"], f"{metric_label}.snapshot_sha256")
            if not _SHA256.fullmatch(snapshot_sha256):
                raise SiteBuildError(f"{metric_label}.snapshot_sha256 must be lowercase SHA-256")
            records_sha256 = _text(metric["records_sha256"], f"{metric_label}.records_sha256")
            if not _SHA256.fullmatch(records_sha256):
                raise SiteBuildError(f"{metric_label}.records_sha256 must be lowercase SHA-256")
            records_file, records_path = _records_path(
                path, metric["records_file"], f"{metric_label}.records_file"
            )
            if records_file in record_payloads:
                raise SiteBuildError(f"{metric_label}.records_file must be unique")
            records, records_raw = _load_records(
                records_path,
                kind=kind,
                expected_sha256=records_sha256,
                label=f"{metric_label}.records_file",
            )
            amount_cents = _positive_int(metric["amount_cents"], f"{metric_label}.amount_cents")
            row_count = _positive_int(metric["row_count"], f"{metric_label}.row_count")
            if row_count != len(records) or amount_cents != sum(
                record.amount_cents for record in records
            ):
                raise SiteBuildError(
                    f"{metric_label} total or row count does not match its records file"
                )
            record_payloads[records_file] = records_raw
            metrics.append(
                Metric(
                    kind=kind,
                    label=_privacy_safe_text(metric["label"], f"{metric_label}.label"),
                    amount_cents=amount_cents,
                    row_count=row_count,
                    row_description=_privacy_safe_text(
                        metric["row_description"], f"{metric_label}.row_description"
                    ),
                    source_title=_privacy_safe_text(
                        metric["source_title"], f"{metric_label}.source_title"
                    ),
                    dataset_id=dataset_id,
                    dataset_url=_official_url(
                        metric["dataset_url"],
                        dataset_id,
                        rows=False,
                        label=f"{metric_label}.dataset_url",
                    ),
                    official_rows_url=_official_url(
                        metric["official_rows_url"],
                        dataset_id,
                        rows=True,
                        label=f"{metric_label}.official_rows_url",
                    ),
                    snapshot_sha256=snapshot_sha256,
                    records_file=records_file,
                    records_sha256=records_sha256,
                    records=records,
                )
            )

        profiles.append(
            Profile(
                slug=slug,
                name=_privacy_safe_text(profile["name"], f"{label}.name"),
                summary=_privacy_safe_text(profile["summary"], f"{label}.summary"),
                identity=identity,
                metrics=tuple(metrics),
                snapshot_date=_privacy_safe_text(
                    profile["snapshot_date"], f"{label}.snapshot_date"
                ),
            )
        )

    lowered = raw.decode("utf-8").casefold()
    prohibited = [field for field in _PROHIBITED_PUBLIC_FIELDS if field in lowered]
    if prohibited:
        raise SiteBuildError(f"site content names prohibited public fields: {prohibited}")
    content_digest = hashlib.sha256(raw)
    for records_file, records_raw in sorted(record_payloads.items()):
        content_digest.update(records_file.encode("utf-8"))
        content_digest.update(b"\0")
        content_digest.update(records_raw)
    return SiteContent(
        beta_notice=beta_notice,
        profiles=tuple(profiles),
        content_sha256=content_digest.hexdigest(),
    )


def _escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def _money(cents: int) -> str:
    return f"${cents / 100:,.2f}"


def _shell(*, title: str, body: str, css_path: str, js_path: str) -> str:
    safe_title = _escape(title)
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="robots" content="noindex,nofollow,noarchive">
    <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'self'; script-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'">
    <meta name="referrer" content="no-referrer">
    <title>{safe_title}</title>
    <link rel="stylesheet" href="/{_escape(css_path)}">
    <script defer src="/{_escape(js_path)}"></script>
  </head>
  <body>
    <a class="skip-link" href="#content">Skip to content</a>
    <header class="site-header">
      <div class="nav-shell">
        <a class="brand" href="/" aria-label="Money on Record home">Money <span>on Record</span></a>
        <span class="environment">Research beta</span>
      </div>
    </header>
    {body}
    <footer class="site-footer">
      <div class="footer-shell">
        <p><strong>Money on Record</strong> organizes public Austin campaign-finance and City spending records.</p>
        <p>Name matches are unverified and do not establish influence or wrongdoing.</p>
      </div>
    </footer>
  </body>
</html>
"""


def _metric(profile: Profile, kind: str) -> Metric:
    return next(metric for metric in profile.metrics if metric.kind == kind)


def _year_range(metric: Metric) -> str:
    years = [int(record.date[:4]) for record in metric.records]
    return str(years[0]) if min(years) == max(years) else f"{min(years)}–{max(years)}"


def _index_page(content: SiteContent, css_path: str, js_path: str) -> str:
    profile_cards = []
    for profile in content.profiles:
        campaign = _metric(profile, "campaign")
        spending = _metric(profile, "spending")
        recipients = {
            record.recipient for record in campaign.records if isinstance(record, CampaignRecord)
        }
        departments = {
            record.department for record in spending.records if isinstance(record, SpendingRecord)
        }
        profile_cards.append(
            f"""<article class="profile-card">
          <p class="status status-small">{_escape(profile.identity.status)}</p>
          <h2><a href="/profiles/{_escape(profile.slug)}/index.html">{_escape(profile.name)}</a></h2>
          <p>{_escape(profile.summary)}</p>
          <dl class="home-totals">
            <div><dt>Campaign disclosures</dt><dd>{_escape(_money(campaign.amount_cents))}</dd><dd>{campaign.row_count} contributions to {len(recipients)} recipient, {_escape(_year_range(campaign))}</dd></div>
            <div><dt>City payments</dt><dd>{_escape(_money(spending.amount_cents))}</dd><dd>{spending.row_count} lines from {len(departments)} departments, {_escape(_year_range(spending))}</dd></div>
          </dl>
          <a class="button" href="/profiles/{_escape(profile.slug)}/index.html">Explore the records</a>
        </article>"""
        )
    body = f"""<main id="content">
      <section class="hero home-hero" aria-labelledby="home-title">
        <p class="kicker">City of Austin public records</p>
        <h1 id="home-title">Austin campaign contributions and City payments</h1>
        <p class="lede">Review public records that use the same organization name across Austin campaign-finance disclosures and the City eCheckbook.</p>
        <div class="beta-callout" role="note">
          <strong>Coverage</strong>
          <span>{_escape(content.beta_notice)}</span>
        </div>
      </section>
      <section class="profiles" aria-labelledby="profiles-title">
        <div class="section-heading">
          <div>
            <p class="kicker">Current dataset</p>
            <h2 id="profiles-title">Records available to review</h2>
          </div>
          <p>{len(content.profiles)} unverified organization-name {"match" if len(content.profiles) == 1 else "matches"}</p>
        </div>
        <div class="profile-grid">
          {"".join(profile_cards)}
        </div>
      </section>
    </main>"""
    return _shell(
        title="Money on Record — Austin public records",
        body=body,
        css_path=css_path,
        js_path=js_path,
    )


def _download_url(metric: Metric) -> str:
    parsed = urlparse(metric.official_rows_url)
    return parsed._replace(path=parsed.path.removesuffix(".json") + ".csv").geturl()


def _spending_row_url(metric: Metric, record: SpendingRecord) -> str:
    fields = parse_qs(urlparse(metric.official_rows_url).query)["$select"][0]
    conditions = (
        ("rfed_doc_cd", record.document_code),
        ("rfed_doc_dept_cd", record.document_department),
        ("rfed_doc_id", record.document_id),
        ("rfed_vend_ln_no", record.vendor_line),
        ("rfed_comm_ln_no", record.commodity_line),
        ("rfed_actg_ln_no", record.accounting_line),
    )
    where = " AND ".join(f"{field} = '{value}'" for field, value in conditions)
    query = urlencode({"$select": fields, "$where": where, "$limit": "1"})
    return f"https://data.austintexas.gov/resource/{metric.dataset_id}.json?{query}"


def _aggregate(
    records: tuple[Record, ...], key: Any, *, years: bool = False
) -> list[tuple[str, int, int]]:
    totals: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for record in records:
        name = str(key(record))
        totals[name][0] += 1
        totals[name][1] += record.amount_cents
    if years:
        order = sorted(totals, reverse=True)
    else:
        order = sorted(totals, key=lambda name: (-totals[name][1], name))
    return [(name, totals[name][0], totals[name][1]) for name in order]


def _breakdown_table(title: str, rows: list[tuple[str, int, int]], total: int) -> str:
    body = "".join(
        f"""<tr><th scope="row">{_escape(label)}</th><td>{count}</td><td class="money">{_escape(_money(amount))}</td><td>{amount * 100 / total:.1f}%</td></tr>"""
        for label, count, amount in rows
    )
    return f"""<article class="breakdown"><h3>{_escape(title)}</h3><div class="table-scroll"><table><thead><tr><th>Group</th><th>Rows</th><th>Amount</th><th>Share</th></tr></thead><tbody>{body}</tbody></table></div></article>"""


def _campaign_browser(metric: Metric) -> str:
    records = [record for record in metric.records if isinstance(record, CampaignRecord)]
    rows = "".join(
        f"""<tr data-record-row data-date="{record.date}" data-amount="{record.amount_cents}" data-search="{_escape(f"{record.date} {record.recipient} {record.type}".casefold())}"><td>{record.date}</td><td>{_escape(record.recipient)}</td><td>{_escape(record.type)}</td><td class="money">{_escape(_money(record.amount_cents))}</td><td><a {_EXTERNAL_LINK_ATTRIBUTES} href="{_escape(record.report_url)}" aria-label="Open official filing for transaction {_escape(record.transaction_id)}">Filing <span aria-hidden="true">↗</span></a></td></tr>"""
        for record in records
    )
    years = _aggregate(metric.records, lambda record: record.date[:4], years=True)
    recipients = _aggregate(
        metric.records,
        lambda record: record.recipient if isinstance(record, CampaignRecord) else "",
    )
    recipient, _, _ = recipients[0]
    return f"""<section class="record-section" aria-labelledby="campaign-title">
      <div class="record-heading"><div><p class="kicker">Campaign-finance disclosures</p><h2 id="campaign-title">{_escape(metric.label)}</h2></div><p class="record-total">{_escape(_money(metric.amount_cents))}<span>{metric.row_count} records · {_escape(_year_range(metric))}</span></p></div>
      <p>All {metric.row_count} entries name <strong>{_escape(recipient)}</strong> as the recipient and classify the support as non-monetary. Amounts are the disclosed contribution amounts.</p>
      <div class="breakdown-grid">{_breakdown_table("Contributions by year", years, metric.amount_cents)}</div>
      <div class="record-browser" data-record-browser>
        <div class="record-controls"><label>Filter contributions<input type="search" data-record-filter placeholder="Date, recipient, or type"></label><label>Sort rows<select data-record-sort><option value="newest">Newest first</option><option value="oldest">Oldest first</option><option value="high">Highest amount</option><option value="low">Lowest amount</option></select></label><p data-record-count aria-live="polite">{metric.row_count} of {metric.row_count} records</p></div>
        <div class="table-scroll"><table class="records-table"><thead><tr><th>Date</th><th>Recipient</th><th>Contribution type</th><th>Amount</th><th>Official record</th></tr></thead><tbody>{rows}</tbody></table></div>
      </div>
      <p class="download"><a {_EXTERNAL_LINK_ATTRIBUTES} href="{_escape(_download_url(metric))}">Download these {metric.row_count} projected official rows as CSV <span aria-hidden="true">↗</span></a></p>
    </section>"""


def _spending_browser(metric: Metric) -> str:
    records = [record for record in metric.records if isinstance(record, SpendingRecord)]
    rows = "".join(
        f"""<tr data-record-row data-date="{record.date}" data-amount="{record.amount_cents}" data-search="{_escape(f"{record.date} {record.department} {record.object}".casefold())}"><td>{record.date}</td><td>{_escape(record.department)}</td><td>{_escape(record.object)}</td><td class="money">{_escape(_money(record.amount_cents))}</td><td><a {_EXTERNAL_LINK_ATTRIBUTES} href="{_escape(_spending_row_url(metric, record))}" aria-label="Open official City row for document {_escape(record.document_id)}">City row <span aria-hidden="true">↗</span></a></td></tr>"""
        for record in records
    )
    departments = _aggregate(
        metric.records,
        lambda record: record.department if isinstance(record, SpendingRecord) else "",
    )
    objects = _aggregate(
        metric.records,
        lambda record: record.object if isinstance(record, SpendingRecord) else "",
    )
    years = _aggregate(metric.records, lambda record: record.date[:4], years=True)
    return f"""<section class="record-section" aria-labelledby="spending-title">
      <div class="record-heading"><div><p class="kicker">City eCheckbook</p><h2 id="spending-title">{_escape(metric.label)}</h2></div><p class="record-total">{_escape(_money(metric.amount_cents))}<span>{metric.row_count} lines · {_escape(_year_range(metric))}</span></p></div>
      <p>The City data provides departments and accounting object categories for these lines, but no line-item descriptions. Amounts are payment-line amounts, not contract totals.</p>
      <div class="breakdown-grid">{_breakdown_table("Payments by department", departments, metric.amount_cents)}{_breakdown_table("Payments by object category", objects, metric.amount_cents)}{_breakdown_table("Payments by year", years, metric.amount_cents)}</div>
      <div class="record-browser" data-record-browser>
        <div class="record-controls"><label>Filter payment lines<input type="search" data-record-filter placeholder="Date, department, or category"></label><label>Sort rows<select data-record-sort><option value="newest">Newest first</option><option value="oldest">Oldest first</option><option value="high">Highest amount</option><option value="low">Lowest amount</option></select></label><p data-record-count aria-live="polite">{metric.row_count} of {metric.row_count} records</p></div>
        <div class="table-scroll"><table class="records-table"><thead><tr><th>Date</th><th>Department</th><th>Object category</th><th>Amount</th><th>Official record</th></tr></thead><tbody>{rows}</tbody></table></div>
      </div>
      <p class="download"><a {_EXTERNAL_LINK_ATTRIBUTES} href="{_escape(_download_url(metric))}">Download these {metric.row_count} projected official rows as CSV <span aria-hidden="true">↗</span></a></p>
    </section>"""


def _profile_page(profile: Profile, beta_notice: str, css_path: str, js_path: str) -> str:
    campaign = _metric(profile, "campaign")
    spending = _metric(profile, "spending")
    source_cards = []
    for metric in profile.metrics:
        source_cards.append(
            f"""<article class="source-card">
          <h3>{_escape(metric.source_title)}</h3>
          <p>City of Austin dataset <code>{_escape(metric.dataset_id)}</code></p>
          <p><a {_EXTERNAL_LINK_ATTRIBUTES} href="{_escape(metric.dataset_url)}">Dataset page <span aria-hidden="true">↗</span></a> · <a {_EXTERNAL_LINK_ATTRIBUTES} href="{_escape(metric.official_rows_url)}">Exact JSON projection <span aria-hidden="true">↗</span></a></p>
          <details><summary>Data fingerprints</summary><dl class="hashes"><dt>Source snapshot</dt><dd><code>{_escape(metric.snapshot_sha256)}</code></dd><dt>Published projection</dt><dd><code>{_escape(metric.records_sha256)}</code></dd></dl></details>
        </article>"""
        )
    body = f"""<main id="content">
      <nav class="breadcrumbs" aria-label="Breadcrumb"><a href="/">Home</a><span aria-hidden="true">/</span><span aria-current="page">{_escape(profile.name)}</span></nav>
      <section class="profile-intro" aria-labelledby="profile-title">
        <p class="status">{_escape(profile.identity.status)}</p>
        <h1 id="profile-title">{_escape(profile.name)}</h1>
        <p class="lede">{_escape(profile.summary)}</p>
        <div class="warning" role="note"><strong>Do not treat this as a confirmed identity.</strong><span>{_escape(profile.identity.explanation)} {_escape(beta_notice)}</span></div>
      </section>
      <section class="summary-grid" aria-label="Record totals">
        <article><p class="eyebrow">Campaign disclosures</p><p class="amount">{_escape(_money(campaign.amount_cents))}</p><p>{campaign.row_count} disclosed contributions, {_escape(_year_range(campaign))}</p><a href="#campaign-title">Review campaign records</a></article>
        <article><p class="eyebrow">City payments</p><p class="amount">{_escape(_money(spending.amount_cents))}</p><p>{spending.row_count} payment lines, {_escape(_year_range(spending))}</p><a href="#spending-title">Review City payment lines</a></article>
      </section>
      {_campaign_browser(campaign)}
      {_spending_browser(spending)}
      <section class="methodology" aria-labelledby="method-title">
        <p class="kicker">Scope and sources</p><h2 id="method-title">How these records were selected</h2>
        <div class="method-grid"><div><h3>Identity boundary</h3><p>The campaign name <strong>{_escape(profile.identity.campaign_name)}</strong> and City vendor name <strong>{_escape(profile.identity.public_spending_name)}</strong> match only after typography and capitalization are normalized. The site does not use person, address, fuzzy-name, or placeholder-code matching.</p><p><strong>{_escape(profile.identity.evidence_tier)}</strong></p></div><div><h3>Calculation</h3><p>For each dataset, the site counts the displayed records and sums their amount fields. The build fails if those calculations differ from the displayed totals.</p><p>Records frozen {_escape(profile.snapshot_date)}.</p></div></div>
        <div class="source-grid">{"".join(source_cards)}</div>
      </section>
    </main>"""
    return _shell(
        title=f"{profile.name} records — Money on Record",
        body=body,
        css_path=css_path,
        js_path=js_path,
    )


def _not_found_page(css_path: str, js_path: str) -> str:
    body = """<main id="content">
      <section class="hero error-page" aria-labelledby="error-title">
        <p class="kicker">404 · Record not found</p>
        <h1 id="error-title">There is no profile at this address.</h1>
        <p class="lede">Check the address or return to the available records.</p>
        <a class="button" href="/">Return to the homepage</a>
      </section>
    </main>"""
    return _shell(
        title="Not found — Money on Record", body=body, css_path=css_path, js_path=js_path
    )


SITE_CSS = """:root {
  color-scheme: light;
  --ink: #17231e;
  --muted: #59665f;
  --paper: #f4f1e9;
  --panel: #fffdf8;
  --line: #ced6d0;
  --green: #145c41;
  --green-dark: #0b3c2a;
  --amber: #765000;
  --amber-soft: #fff2ca;
}

* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body { margin: 0; color: var(--ink); background: var(--paper); font: 16px/1.55 Inter, ui-sans-serif, system-ui, sans-serif; }
a { color: var(--green); text-underline-offset: .2em; }
a:hover { color: var(--green-dark); }
a:focus-visible, input:focus-visible, select:focus-visible, summary:focus-visible { outline: 3px solid #c47e00; outline-offset: 3px; }
.skip-link { position: fixed; top: 8px; left: 8px; z-index: 10; padding: 10px 14px; background: var(--ink); color: white; transform: translateY(-160%); }
.skip-link:focus { transform: none; }
.site-header { border-bottom: 1px solid var(--line); background: var(--panel); }
.nav-shell, main, .footer-shell { width: min(1180px, calc(100% - 32px)); margin-inline: auto; }
.nav-shell { min-height: 68px; display: flex; align-items: center; justify-content: space-between; gap: 24px; }
.brand { color: var(--ink); font: 700 1.2rem Georgia, serif; text-decoration: none; }
.brand span { color: var(--green); }
.environment, .status { border: 1px solid #dfb95e; border-radius: 999px; color: var(--amber); background: var(--amber-soft); font-size: .72rem; font-weight: 800; letter-spacing: .06em; text-transform: uppercase; }
.environment { padding: 5px 9px; }
.status { display: inline-flex; width: fit-content; margin: 0; padding: 7px 11px; }
.status-small { padding: 4px 8px; font-size: .66rem; }
main { padding-block: 38px 72px; }
.hero, .profile-intro { padding-block: 34px 42px; }
.home-hero { max-width: 900px; padding-block: 64px 54px; }
.kicker, .eyebrow { margin: 0 0 9px; color: #2e5874; font-size: .76rem; font-weight: 800; letter-spacing: .08em; text-transform: uppercase; }
h1, h2, h3, p, dd, th, td { overflow-wrap: anywhere; }
h1 { max-width: 960px; margin: 12px 0 18px; font: 700 clamp(2.6rem, 6vw, 4.8rem)/1 Georgia, serif; letter-spacing: -.04em; }
h2 { margin: 0; font: 700 clamp(1.55rem, 3vw, 2.1rem)/1.15 Georgia, serif; letter-spacing: -.02em; }
h3 { margin: 0 0 10px; font-size: 1rem; }
.lede { max-width: 800px; margin: 0; color: var(--muted); font-size: clamp(1.02rem, 2vw, 1.2rem); }
.beta-callout, .warning { display: grid; grid-template-columns: max-content 1fr; gap: 16px; max-width: 920px; margin-top: 26px; padding: 17px 19px; border-left: 4px solid #c78b18; background: #fff8e7; }
.beta-callout strong, .warning strong { color: var(--amber); }
.profiles { margin-top: 24px; }
.section-heading, .record-heading { display: flex; align-items: end; justify-content: space-between; gap: 28px; margin-bottom: 20px; }
.section-heading > p { margin: 0; color: var(--muted); }
.profile-grid { display: grid; gap: 18px; }
.profile-card, .summary-grid article, .record-section, .methodology { border: 1px solid var(--line); border-radius: 14px; background: var(--panel); }
.profile-card { padding: clamp(24px, 4vw, 36px); }
.profile-card h2 { margin: 17px 0 8px; }
.profile-card h2 a { color: var(--ink); }
.profile-card > p:not(.status) { color: var(--muted); }
.home-totals { display: grid; grid-template-columns: repeat(2, 1fr); gap: 18px; margin: 24px 0 0; }
.home-totals div { padding-top: 14px; border-top: 1px solid var(--line); }
.home-totals dt { color: var(--muted); font-size: .78rem; }
.home-totals dd { margin: 2px 0 0; }
.home-totals dd:first-of-type { font: 700 1.75rem Georgia, serif; }
.button { display: inline-block; width: fit-content; margin-top: 24px; padding: 11px 16px; border-radius: 7px; color: white; background: var(--green); font-weight: 750; text-decoration: none; }
.button:hover { color: white; background: var(--green-dark); }
.breadcrumbs { display: flex; gap: 10px; align-items: center; color: var(--muted); font-size: .86rem; }
.summary-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 18px; margin-bottom: 26px; }
.summary-grid article { padding: 24px; }
.amount, .record-total { margin: 6px 0; font: 700 clamp(2.1rem, 4vw, 3.1rem)/1 Georgia, serif; letter-spacing: -.035em; }
.summary-grid article > p:not(.eyebrow, .amount) { color: var(--muted); }
.record-section, .methodology { margin-top: 24px; padding: clamp(22px, 4vw, 36px); }
.record-section > p { max-width: 850px; color: var(--muted); }
.record-total { text-align: right; }
.record-total span { display: block; margin-top: 7px; color: var(--muted); font: 400 .86rem/1.3 Inter, sans-serif; letter-spacing: 0; }
.breakdown-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; margin: 26px 0; }
.breakdown { min-width: 0; padding: 18px; border: 1px solid var(--line); border-radius: 10px; }
.breakdown-grid .breakdown:last-child:nth-child(3) { grid-column: 1 / -1; }
.table-scroll { max-width: 100%; overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: .87rem; }
th, td { padding: 10px 9px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }
thead th { color: var(--muted); font-size: .72rem; letter-spacing: .04em; text-transform: uppercase; }
tbody tr:last-child > * { border-bottom: 0; }
.money { white-space: nowrap; text-align: right; font-variant-numeric: tabular-nums; }
.record-browser { margin-top: 28px; }
.record-controls { display: grid; grid-template-columns: minmax(220px, 1fr) minmax(180px, 260px) auto; gap: 14px; align-items: end; margin-bottom: 14px; }
.record-controls label { color: var(--muted); font-size: .78rem; font-weight: 700; }
input, select { width: 100%; margin-top: 5px; padding: 10px 11px; border: 1px solid #aebbb3; border-radius: 6px; color: var(--ink); background: white; font: inherit; }
.record-controls p { margin: 0 0 10px; color: var(--muted); font-size: .82rem; white-space: nowrap; }
.records-table { min-width: 800px; }
.records-table tbody tr:nth-child(even) { background: #f7f7f2; }
.download { margin-bottom: 0; font-size: .87rem; }
.methodology > h2 { margin-bottom: 22px; }
.method-grid, .source-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; }
.method-grid > div, .source-card { padding: 20px; border: 1px solid var(--line); border-radius: 10px; }
.method-grid p, .source-card p { color: var(--muted); }
.source-grid { margin-top: 18px; }
.source-card details { margin-top: 14px; }
.source-card summary { cursor: pointer; }
.hashes { display: grid; gap: 5px; }
.hashes dt { margin-top: 7px; color: var(--muted); font-size: .75rem; }
.hashes dd { margin: 0; }
code { color: #33473d; font-size: .72rem; overflow-wrap: anywhere; }
[hidden] { display: none; }
.error-page { min-height: 55vh; display: flex; flex-direction: column; justify-content: center; }
.site-footer { border-top: 1px solid var(--line); color: var(--muted); font-size: .84rem; }
.footer-shell { display: grid; grid-template-columns: 1fr 1fr; gap: 32px; padding-block: 28px 40px; }
.footer-shell p { margin: 0; }

@media (max-width: 760px) {
  main { padding-top: 26px; }
  .home-hero { padding-block: 44px; }
  .home-totals, .summary-grid, .breakdown-grid, .method-grid, .source-grid { grid-template-columns: 1fr; }
  .breakdown-grid .breakdown:last-child:nth-child(3) { grid-column: auto; }
  .beta-callout, .warning, .record-controls { grid-template-columns: 1fr; }
  .section-heading, .record-heading { display: block; }
  .section-heading > p, .record-total { margin-top: 10px; text-align: left; }
  .record-controls p { margin: 0; }
  .footer-shell { grid-template-columns: 1fr; gap: 10px; }
}

@media (prefers-reduced-motion: reduce) { html { scroll-behavior: auto; } }
"""


SITE_JS = """document.querySelectorAll('[data-record-browser]').forEach((browser) => {
  const filter = browser.querySelector('[data-record-filter]');
  const sort = browser.querySelector('[data-record-sort]');
  const count = browser.querySelector('[data-record-count]');
  const body = browser.querySelector('tbody');
  const rows = Array.from(browser.querySelectorAll('[data-record-row]'));

  const update = () => {
    const query = filter.value.trim().toLocaleLowerCase();
    const direction = sort.value;
    rows.sort((left, right) => {
      if (direction === 'high' || direction === 'low') {
        const result = Number(left.dataset.amount) - Number(right.dataset.amount);
        return direction === 'high' ? -result : result;
      }
      const result = left.dataset.date.localeCompare(right.dataset.date);
      return direction === 'newest' ? -result : result;
    });
    let visible = 0;
    rows.forEach((row) => {
      row.hidden = !row.dataset.search.includes(query);
      visible += row.hidden ? 0 : 1;
      body.append(row);
    });
    count.textContent = `${visible} of ${rows.length} records`;
  };

  filter.addEventListener('input', update);
  sort.addEventListener('change', update);
});
"""


def _write_site(output: Path, content: SiteContent) -> dict[str, bytes]:
    css_bytes = SITE_CSS.encode("utf-8")
    css_digest = hashlib.sha256(css_bytes).hexdigest()[:16]
    css_path = f"assets/site-{css_digest}.css"
    js_bytes = SITE_JS.encode("utf-8")
    js_digest = hashlib.sha256(js_bytes).hexdigest()[:16]
    js_path = f"assets/site-{js_digest}.js"
    files: dict[str, bytes] = {
        css_path: css_bytes,
        js_path: js_bytes,
        "index.html": _index_page(content, css_path, js_path).encode("utf-8"),
        "404.html": _not_found_page(css_path, js_path).encode("utf-8"),
        "robots.txt": b"User-agent: *\nDisallow: /\n",
    }
    for profile in content.profiles:
        files[f"profiles/{profile.slug}/index.html"] = _profile_page(
            profile, content.beta_notice, css_path, js_path
        ).encode("utf-8")

    manifest = {
        "schema_version": SITE_SCHEMA_VERSION,
        "content_sha256": content.content_sha256,
        "files": {
            name: {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            for name, data in sorted(files.items())
        },
        "profiles": [profile.slug for profile in content.profiles],
        "source_snapshots": sorted(
            {metric.snapshot_sha256 for profile in content.profiles for metric in profile.metrics}
        ),
    }
    files[MANIFEST_NAME] = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()

    for name, data in sorted(files.items()):
        destination = output / PurePosixPath(name)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        destination.chmod(0o644)
    return files


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
    content = load_site_content(content_path)
    output.mkdir(parents=True)
    files = _write_site(output, content)
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
