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
from datetime import date, datetime
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

from .privacy import contains_pii

SITE_SCHEMA_VERSION = 1
CONTENT_SCHEMA_VERSION = 4
RECORD_SCHEMA_VERSION = 1
CAMPAIGN_PUBLICATION_SCHEMA_VERSION = 1
MANIFEST_NAME = "site-manifest.json"
MAX_ARCHIVE_FILES = 250
MAX_ARCHIVE_BYTES = 32 * 1024 * 1024
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
    jurisdiction: str
    summary: str
    identity: Identity
    metrics: tuple[Metric, ...]
    snapshot_date: str


@dataclass(frozen=True)
class PublicationSource:
    slug: str
    dataset_id: str
    title: str
    dataset_url: str
    artifact_sha256: str
    retrieved_at: str


@dataclass(frozen=True)
class PublishedContribution:
    amount_cents: int
    correction: bool
    date: str
    donor: str
    donor_type: str
    report_url: str
    transaction_id: str
    type: str


@dataclass(frozen=True)
class DonorSummary:
    name: str
    donor_type: str
    row_count: int
    amount_cents: int


@dataclass(frozen=True)
class YearSummary:
    year: str
    row_count: int
    amount_cents: int


@dataclass(frozen=True)
class CampaignProfile:
    slug: str
    name: str
    source_names: tuple[str, ...]
    classification: str
    office_held: tuple[str, ...]
    office_sought: tuple[str, ...]
    amount_cents: int
    row_count: int
    donor_count: int
    correction_row_count: int
    correction_amount_cents: int
    first_date: str
    last_date: str
    official_rows_url: str
    top_donors: tuple[DonorSummary, ...]
    by_year: tuple[YearSummary, ...]
    sample_records: tuple[PublishedContribution, ...]


@dataclass(frozen=True)
class CampaignPublication:
    jurisdiction: str
    sample_limit: int
    snapshot_date: str
    sources: tuple[PublicationSource, ...]
    raw_row_count: int
    published_row_count: int
    excluded_blank_recipient_rows: int
    campaign_count: int
    donor_count: int
    amount_cents: int
    correction_row_count: int
    campaigns: tuple[CampaignProfile, ...]


@dataclass(frozen=True)
class SiteContent:
    beta_notice: str
    campaign_publication: CampaignPublication
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


def _nonnegative_int(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise SiteBuildError(f"{label} must be a non-negative integer")
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


def _text_list(value: object, label: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list) or (not value and not allow_empty):
        raise SiteBuildError(
            f"{label} must be a{' possibly empty' if allow_empty else ' non-empty'} list"
        )
    items = tuple(_privacy_safe_text(item, f"{label}[{index}]") for index, item in enumerate(value))
    if len(items) != len(set(items)):
        raise SiteBuildError(f"{label} must not contain duplicates")
    return items


def _load_campaign_publication(
    path: Path, *, expected_sha256: str, label: str
) -> tuple[CampaignPublication, bytes]:
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise SiteBuildError(f"{label} does not match sha256")
    try:
        document = _mapping(json.loads(raw), label)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise SiteBuildError(f"{label} is not valid UTF-8 JSON") from error
    _exact_keys(
        document,
        {
            "schema_version",
            "jurisdiction",
            "sample_limit",
            "snapshot_date",
            "sources",
            "raw_row_count",
            "published_row_count",
            "excluded_blank_recipient_rows",
            "campaign_count",
            "donor_count",
            "amount_cents",
            "correction_row_count",
            "campaigns",
        },
        label,
    )
    if document["schema_version"] != CAMPAIGN_PUBLICATION_SCHEMA_VERSION:
        raise SiteBuildError(f"{label} has an unsupported schema version")
    sample_limit = _positive_int(document["sample_limit"], f"{label}.sample_limit")
    if sample_limit > 500:
        raise SiteBuildError(f"{label}.sample_limit exceeds the publication bound")

    raw_sources = document["sources"]
    if not isinstance(raw_sources, list) or len(raw_sources) != 2:
        raise SiteBuildError(f"{label}.sources must contain contributions and reports")
    sources: list[PublicationSource] = []
    source_slugs: set[str] = set()
    for index, raw_source in enumerate(raw_sources):
        source_label = f"{label}.sources[{index}]"
        source = _mapping(raw_source, source_label)
        _exact_keys(
            source,
            {
                "slug",
                "dataset_id",
                "title",
                "dataset_url",
                "artifact_sha256",
                "retrieved_at",
            },
            source_label,
        )
        slug = _text(source["slug"], f"{source_label}.slug")
        if slug in source_slugs:
            raise SiteBuildError(f"{source_label}.slug must be unique")
        source_slugs.add(slug)
        dataset_id = _text(source["dataset_id"], f"{source_label}.dataset_id")
        if not re.fullmatch(r"[a-z0-9]{4}-[a-z0-9]{4}", dataset_id):
            raise SiteBuildError(f"{source_label}.dataset_id is invalid")
        artifact_sha256 = _text(source["artifact_sha256"], f"{source_label}.artifact_sha256")
        if not _SHA256.fullmatch(artifact_sha256):
            raise SiteBuildError(f"{source_label}.artifact_sha256 must be lowercase SHA-256")
        retrieved_at = _text(source["retrieved_at"], f"{source_label}.retrieved_at")
        try:
            datetime.fromisoformat(retrieved_at)
        except ValueError as error:
            raise SiteBuildError(f"{source_label}.retrieved_at must be ISO-8601") from error
        sources.append(
            PublicationSource(
                slug=slug,
                dataset_id=dataset_id,
                title=_privacy_safe_text(source["title"], f"{source_label}.title"),
                dataset_url=_official_url(
                    source["dataset_url"],
                    dataset_id,
                    rows=False,
                    label=f"{source_label}.dataset_url",
                ),
                artifact_sha256=artifact_sha256,
                retrieved_at=retrieved_at,
            )
        )
    if source_slugs != {"campaign-contributions", "campaign-reports"}:
        raise SiteBuildError(f"{label}.sources must be campaign contributions and reports")

    raw_campaigns = document["campaigns"]
    if not isinstance(raw_campaigns, list) or not raw_campaigns:
        raise SiteBuildError(f"{label}.campaigns must be a non-empty list")
    campaigns: list[CampaignProfile] = []
    slugs: set[str] = set()
    sampled_transaction_ids: set[str] = set()
    for campaign_index, raw_campaign in enumerate(raw_campaigns):
        campaign_label = f"{label}.campaigns[{campaign_index}]"
        campaign = _mapping(raw_campaign, campaign_label)
        _exact_keys(
            campaign,
            {
                "slug",
                "name",
                "source_names",
                "classification",
                "office_held",
                "office_sought",
                "amount_cents",
                "row_count",
                "donor_count",
                "correction_row_count",
                "correction_amount_cents",
                "first_date",
                "last_date",
                "official_rows_url",
                "top_donors",
                "by_year",
                "sample_records",
            },
            campaign_label,
        )
        slug = _text(campaign["slug"], f"{campaign_label}.slug")
        if not _SLUG.fullmatch(slug) or slug in slugs:
            raise SiteBuildError(f"{campaign_label}.slug must be unique lowercase kebab-case")
        slugs.add(slug)
        classification = _privacy_safe_text(
            campaign["classification"], f"{campaign_label}.classification"
        )
        if classification not in {
            "Candidate or officeholder",
            "Political committee",
            "Campaign recipient",
        }:
            raise SiteBuildError(f"{campaign_label}.classification is unsupported")
        amount_cents = _nonnegative_int(campaign["amount_cents"], f"{campaign_label}.amount_cents")
        row_count = _positive_int(campaign["row_count"], f"{campaign_label}.row_count")
        donor_count = _positive_int(campaign["donor_count"], f"{campaign_label}.donor_count")
        correction_row_count = _nonnegative_int(
            campaign["correction_row_count"], f"{campaign_label}.correction_row_count"
        )
        correction_amount_cents = _nonnegative_int(
            campaign["correction_amount_cents"],
            f"{campaign_label}.correction_amount_cents",
        )
        if correction_row_count > row_count or correction_amount_cents > amount_cents:
            raise SiteBuildError(f"{campaign_label} correction totals exceed campaign totals")

        raw_donors = campaign["top_donors"]
        if not isinstance(raw_donors, list) or not raw_donors or len(raw_donors) > 20:
            raise SiteBuildError(f"{campaign_label}.top_donors must contain 1 to 20 rows")
        donors: list[DonorSummary] = []
        for donor_index, raw_donor in enumerate(raw_donors):
            donor_label = f"{campaign_label}.top_donors[{donor_index}]"
            donor = _mapping(raw_donor, donor_label)
            _exact_keys(
                donor,
                {"name", "donor_type", "row_count", "amount_cents"},
                donor_label,
            )
            donor_type = _text(donor["donor_type"], f"{donor_label}.donor_type")
            if donor_type not in {"ENTITY", "INDIVIDUAL"}:
                raise SiteBuildError(f"{donor_label}.donor_type is unsupported")
            donors.append(
                DonorSummary(
                    name=_privacy_safe_text(donor["name"], f"{donor_label}.name"),
                    donor_type=donor_type,
                    row_count=_positive_int(donor["row_count"], f"{donor_label}.row_count"),
                    amount_cents=_nonnegative_int(
                        donor["amount_cents"], f"{donor_label}.amount_cents"
                    ),
                )
            )

        raw_years = campaign["by_year"]
        if not isinstance(raw_years, list) or not raw_years:
            raise SiteBuildError(f"{campaign_label}.by_year must be a non-empty list")
        years: list[YearSummary] = []
        for year_index, raw_year in enumerate(raw_years):
            year_label = f"{campaign_label}.by_year[{year_index}]"
            year = _mapping(raw_year, year_label)
            _exact_keys(year, {"year", "row_count", "amount_cents"}, year_label)
            year_text = _text(year["year"], f"{year_label}.year")
            if not re.fullmatch(r"\d{4}", year_text):
                raise SiteBuildError(f"{year_label}.year is invalid")
            years.append(
                YearSummary(
                    year=year_text,
                    row_count=_positive_int(year["row_count"], f"{year_label}.row_count"),
                    amount_cents=_nonnegative_int(
                        year["amount_cents"], f"{year_label}.amount_cents"
                    ),
                )
            )
        if (
            sum(year.row_count for year in years) != row_count
            or sum(year.amount_cents for year in years) != amount_cents
        ):
            raise SiteBuildError(f"{campaign_label}.by_year does not match campaign totals")

        raw_samples = campaign["sample_records"]
        if not isinstance(raw_samples, list) or len(raw_samples) != min(row_count, sample_limit):
            raise SiteBuildError(f"{campaign_label}.sample_records has the wrong row count")
        samples: list[PublishedContribution] = []
        for record_index, raw_record in enumerate(raw_samples):
            record_label = f"{campaign_label}.sample_records[{record_index}]"
            record = _mapping(raw_record, record_label)
            _exact_keys(
                record,
                {
                    "amount_cents",
                    "correction",
                    "date",
                    "donor",
                    "donor_type",
                    "report_url",
                    "transaction_id",
                    "type",
                },
                record_label,
            )
            if not isinstance(record["correction"], bool):
                raise SiteBuildError(f"{record_label}.correction must be boolean")
            transaction_id = _text(record["transaction_id"], f"{record_label}.transaction_id")
            if transaction_id in sampled_transaction_ids:
                raise SiteBuildError(f"{record_label}.transaction_id must be globally unique")
            sampled_transaction_ids.add(transaction_id)
            donor_type = _text(record["donor_type"], f"{record_label}.donor_type")
            if donor_type not in {"ENTITY", "INDIVIDUAL"}:
                raise SiteBuildError(f"{record_label}.donor_type is unsupported")
            samples.append(
                PublishedContribution(
                    amount_cents=_nonnegative_int(
                        record["amount_cents"], f"{record_label}.amount_cents"
                    ),
                    correction=record["correction"],
                    date=_date_text(record["date"], f"{record_label}.date"),
                    donor=_privacy_safe_text(record["donor"], f"{record_label}.donor"),
                    donor_type=donor_type,
                    report_url=_report_url(record["report_url"], f"{record_label}.report_url"),
                    transaction_id=transaction_id,
                    type=_privacy_safe_text(record["type"], f"{record_label}.type"),
                )
            )
        first_date = _date_text(campaign["first_date"], f"{campaign_label}.first_date")
        last_date = _date_text(campaign["last_date"], f"{campaign_label}.last_date")
        if first_date > last_date:
            raise SiteBuildError(f"{campaign_label} date range is reversed")
        campaigns.append(
            CampaignProfile(
                slug=slug,
                name=_privacy_safe_text(campaign["name"], f"{campaign_label}.name"),
                source_names=_text_list(campaign["source_names"], f"{campaign_label}.source_names"),
                classification=classification,
                office_held=_text_list(
                    campaign["office_held"],
                    f"{campaign_label}.office_held",
                    allow_empty=True,
                ),
                office_sought=_text_list(
                    campaign["office_sought"],
                    f"{campaign_label}.office_sought",
                    allow_empty=True,
                ),
                amount_cents=amount_cents,
                row_count=row_count,
                donor_count=donor_count,
                correction_row_count=correction_row_count,
                correction_amount_cents=correction_amount_cents,
                first_date=first_date,
                last_date=last_date,
                official_rows_url=_official_url(
                    campaign["official_rows_url"],
                    "3kfv-biw6",
                    rows=True,
                    label=f"{campaign_label}.official_rows_url",
                ),
                top_donors=tuple(donors),
                by_year=tuple(years),
                sample_records=tuple(samples),
            )
        )

    campaign_count = _positive_int(document["campaign_count"], f"{label}.campaign_count")
    published_row_count = _positive_int(
        document["published_row_count"], f"{label}.published_row_count"
    )
    amount_cents = _nonnegative_int(document["amount_cents"], f"{label}.amount_cents")
    correction_row_count = _nonnegative_int(
        document["correction_row_count"], f"{label}.correction_row_count"
    )
    excluded_rows = _nonnegative_int(
        document["excluded_blank_recipient_rows"],
        f"{label}.excluded_blank_recipient_rows",
    )
    raw_row_count = _positive_int(document["raw_row_count"], f"{label}.raw_row_count")
    if (
        campaign_count != len(campaigns)
        or published_row_count != sum(campaign.row_count for campaign in campaigns)
        or amount_cents != sum(campaign.amount_cents for campaign in campaigns)
        or correction_row_count != sum(campaign.correction_row_count for campaign in campaigns)
        or raw_row_count != published_row_count + excluded_rows
    ):
        raise SiteBuildError(f"{label} aggregate totals do not match its campaign profiles")
    snapshot_date = _date_text(document["snapshot_date"], f"{label}.snapshot_date")
    if snapshot_date != max(campaign.last_date for campaign in campaigns):
        raise SiteBuildError(f"{label}.snapshot_date does not match the latest campaign row")
    lowered = raw.decode("utf-8").casefold()
    prohibited = [field for field in _PROHIBITED_PUBLIC_FIELDS if field in lowered]
    if prohibited:
        raise SiteBuildError(f"{label} names prohibited public fields: {prohibited}")
    return (
        CampaignPublication(
            jurisdiction=_privacy_safe_text(document["jurisdiction"], f"{label}.jurisdiction"),
            sample_limit=sample_limit,
            snapshot_date=snapshot_date,
            sources=tuple(sources),
            raw_row_count=raw_row_count,
            published_row_count=published_row_count,
            excluded_blank_recipient_rows=excluded_rows,
            campaign_count=campaign_count,
            donor_count=_positive_int(document["donor_count"], f"{label}.donor_count"),
            amount_cents=amount_cents,
            correction_row_count=correction_row_count,
            campaigns=tuple(campaigns),
        ),
        raw,
    )


def load_site_content(path: Path) -> SiteContent:
    raw = path.read_bytes()
    try:
        document = _mapping(json.loads(raw), "site content")
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise SiteBuildError(f"{path} is not valid UTF-8 JSON") from error

    _exact_keys(
        document,
        {"schema_version", "beta_notice", "campaign_publication", "profiles"},
        "site content",
    )
    if document["schema_version"] != CONTENT_SCHEMA_VERSION:
        raise SiteBuildError(f"site content schema must be {CONTENT_SCHEMA_VERSION}")
    beta_notice = _privacy_safe_text(document["beta_notice"], "beta_notice")
    raw_profiles = document["profiles"]
    if not isinstance(raw_profiles, list) or not raw_profiles:
        raise SiteBuildError("profiles must be a non-empty list")
    publication_reference = _mapping(document["campaign_publication"], "campaign_publication")
    _exact_keys(publication_reference, {"file", "sha256"}, "campaign_publication")
    publication_sha256 = _text(publication_reference["sha256"], "campaign_publication.sha256")
    if not _SHA256.fullmatch(publication_sha256):
        raise SiteBuildError("campaign_publication.sha256 must be lowercase SHA-256")
    publication_file, publication_path = _records_path(
        path, publication_reference["file"], "campaign_publication.file"
    )
    campaign_publication, publication_raw = _load_campaign_publication(
        publication_path,
        expected_sha256=publication_sha256,
        label="campaign_publication.file",
    )
    profiles: list[Profile] = []
    record_payloads: dict[str, bytes] = {publication_file: publication_raw}
    slugs: set[str] = set()
    for profile_index, raw_profile in enumerate(raw_profiles):
        label = f"profiles[{profile_index}]"
        profile = _mapping(raw_profile, label)
        _exact_keys(
            profile,
            {
                "slug",
                "name",
                "jurisdiction",
                "summary",
                "identity",
                "metrics",
                "snapshot_date",
            },
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
                jurisdiction=_privacy_safe_text(profile["jurisdiction"], f"{label}.jurisdiction"),
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
        campaign_publication=campaign_publication,
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
        <a class="brand" href="/" aria-label="Money on Record home">Money on Record</a>
        <nav aria-label="Primary navigation"><a href="/#campaigns">Explore data</a><span>Research beta</span></nav>
      </div>
    </header>
    {body}
    <footer class="site-footer">
      <div class="footer-shell">
        <p><strong>Money on Record</strong> organizes government records for public-interest research.</p>
        <p>Public records can contain errors. Cross-source name matches remain unverified.</p>
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


def _display_date(value: str) -> str:
    parsed = date.fromisoformat(value)
    return f"{parsed.strftime('%B')} {parsed.day}, {parsed.year}"


def _office_label(value: str) -> str:
    match = re.search(r"COUNCIL_MBR_DISTRICT_0?(\d+)", value)
    if match:
        return f"Austin City Council District {int(match.group(1))}"
    if "MAYOR" in value.upper():
        return "Mayor of Austin"
    return value.replace("_", " ").title()


def _campaign_office(campaign: CampaignProfile) -> str:
    values = campaign.office_sought or campaign.office_held
    labels = tuple(dict.fromkeys(_office_label(value) for value in values))
    return ", ".join(labels) or "Not specified in matched reports"


def _index_page(content: SiteContent, css_path: str, js_path: str) -> str:
    publication = content.campaign_publication
    campaign_rows = []
    for campaign in publication.campaigns:
        office = _campaign_office(campaign)
        search = f"{campaign.name} {campaign.classification} {office}".casefold()
        campaign_rows.append(
            f"""<tr data-directory-row data-directory-search="{_escape(search)}"><th scope="row"><a href="/campaigns/{_escape(campaign.slug)}/index.html">{_escape(campaign.name)}</a><span class="table-status neutral-status">{_escape(campaign.classification)}</span></th><td data-label="Office">{_escape(office)}</td><td class="numeric" data-label="Reported contributions"><strong>{_escape(_money(campaign.amount_cents))}</strong><span>{campaign.row_count:,} rows</span></td><td class="numeric" data-label="Donors"><strong>{campaign.donor_count:,}</strong><span>reported names</span></td><td data-label="Latest activity">{_escape(_display_date(campaign.last_date))}</td><td class="directory-action"><a href="/campaigns/{_escape(campaign.slug)}/index.html" aria-label="View campaign records for {_escape(campaign.name)}">View records <span aria-hidden="true">→</span></a></td></tr>"""
        )

    profile_rows = []
    for profile in content.profiles:
        campaign = _metric(profile, "campaign")
        spending = _metric(profile, "spending")
        profile_rows.append(
            f"""<tr><th scope="row"><a href="/profiles/{_escape(profile.slug)}/index.html">{_escape(profile.name)}</a><span class="table-status">{_escape(profile.identity.status)}</span></th><td data-label="Jurisdiction">{_escape(profile.jurisdiction)}</td><td class="numeric" data-label="Campaign disclosures"><strong>{_escape(_money(campaign.amount_cents))}</strong><span>{campaign.row_count} records</span></td><td class="numeric" data-label="Government payments"><strong>{_escape(_money(spending.amount_cents))}</strong><span>{spending.row_count} records</span></td><td class="directory-action"><a href="/profiles/{_escape(profile.slug)}/index.html" aria-label="View records for {_escape(profile.name)}">View linked records <span aria-hidden="true">→</span></a></td></tr>"""
        )
    body = f"""<main id="content">
      <section class="home-intro" aria-labelledby="home-title">
        <div class="home-intro-copy"><p class="section-label">Austin campaign finance</p>
        <h1 id="home-title">Campaign contributions reported in Austin</h1>
        <p class="lede">Search candidates, officeholders, and political committees. Review reported contributors, amounts, dates, and original City filings.</p></div>
        <p class="database-meta"><strong>Records through {_escape(_display_date(publication.snapshot_date))}</strong><span>{publication.campaign_count} recipients</span><span>{publication.published_row_count:,} contribution rows</span></p>
      </section>
      <section class="directory" id="campaigns" aria-labelledby="directory-title">
        <div class="directory-search">
          <label for="campaign-search">Search candidates and committees</label>
          <div><input id="campaign-search" type="search" data-directory-filter placeholder="Name, office, district, or committee"><button type="button" data-directory-submit>Search</button></div>
          <p>City Clerk campaign-finance records filed from 2022 through 2026.</p>
        </div>
        <div class="directory-heading"><div><p class="section-label">Browse the data</p><h2 id="directory-title">Candidates and committees</h2></div><p data-directory-count>{publication.campaign_count} results</p></div>
        <div class="table-scroll directory-table campaign-directory"><table><thead><tr><th>Recipient</th><th>Office</th><th>Reported contributions</th><th>Donors</th><th>Latest activity</th><th></th></tr></thead><tbody>{"".join(campaign_rows)}</tbody></table></div>
        <p class="table-caption">Recipient classifications and offices come from exact typography-normalized matches to City campaign-report filer names. They do not merge people or infer identities.</p>
      </section>
      <section class="linked-records" id="organizations" aria-labelledby="organizations-title">
        <div class="section-heading"><div><p class="section-label">Linked public records</p><h2 id="organizations-title">Organizations also found in City spending</h2></div><p>{len(content.profiles)} reviewed example</p></div>
        <p class="section-intro">These profiles connect an organization name in campaign records with a matching City vendor name. Every cross-source match remains visibly unverified.</p>
        <div class="table-scroll directory-table"><table><thead><tr><th>Organization</th><th>Jurisdiction</th><th>Campaign disclosures</th><th>Government payments</th><th></th></tr></thead><tbody>{"".join(profile_rows)}</tbody></table></div>
      </section>
      <section class="coverage" aria-labelledby="coverage-title">
        <div><p class="section-label">Coverage and limits</p><h2 id="coverage-title">What is included</h2><p>Campaign totals are sums of published rows, not audited net receipts. Correction-marked filings are retained and labeled because the public projection does not identify a reliable superseded row.</p></div>
        <dl><div><dt>Campaign contributions</dt><dd>{publication.published_row_count:,} rows across {publication.campaign_count} recipients</dd><dd>{publication.correction_row_count:,} rows are marked as corrections</dd></div><div><dt>Row-level display</dt><dd>Up to {publication.sample_limit} most recent rows per recipient</dd><dd>Full projected records remain available from the official City dataset</dd></div></dl>
      </section>
    </main>"""
    return _shell(
        title="Austin campaign contributions — Money on Record",
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
        f"""<tr><th scope="row">{_escape(label)}</th><td>{count}</td><td class="money">{_escape(_money(amount))}</td><td class="share"><meter min="0" max="{total}" value="{amount}" aria-label="{amount * 100 / total:.1f} percent of total"></meter><span>{amount * 100 / total:.1f}%</span></td></tr>"""
        for label, count, amount in rows
    )
    return f"""<section class="breakdown"><h3>{_escape(title)}</h3><div class="table-scroll"><table><thead><tr><th>Group</th><th>Rows</th><th>Amount</th><th>Share</th></tr></thead><tbody>{body}</tbody></table></div></section>"""


def _filter_options(values: set[str]) -> str:
    return "".join(
        f'<option value="{_escape(value.casefold())}">{_escape(value)}</option>'
        for value in sorted(values)
    )


def _campaign_browser(metric: Metric) -> str:
    records = [record for record in metric.records if isinstance(record, CampaignRecord)]
    rows = "".join(
        f"""<tr data-record-row data-year="{record.date[:4]}" data-date="{record.date}" data-amount="{record.amount_cents}" data-search="{_escape(f"{record.date} {record.recipient} {record.type}".casefold())}"><td>{record.date}</td><td>{_escape(record.recipient)}</td><td>{_escape(record.type)}</td><td class="money">{_escape(_money(record.amount_cents))}</td><td><a {_EXTERNAL_LINK_ATTRIBUTES} href="{_escape(record.report_url)}" aria-label="Open official filing for transaction {_escape(record.transaction_id)}">Filing <span aria-hidden="true">↗</span></a></td></tr>"""
        for record in records
    )
    years = _aggregate(metric.records, lambda record: record.date[:4], years=True)
    recipients = _aggregate(
        metric.records,
        lambda record: record.recipient if isinstance(record, CampaignRecord) else "",
    )
    recipient, _, _ = recipients[0]
    year_options = _filter_options({record.date[:4] for record in records})
    return f"""<section class="record-section" id="campaign" aria-labelledby="campaign-title">
      <div class="record-heading"><div><p class="section-label">Campaign finance</p><h2 id="campaign-title">Contribution disclosures</h2></div><a class="download-link" {_EXTERNAL_LINK_ATTRIBUTES} href="{_escape(_download_url(metric))}">Download CSV <span aria-hidden="true">↓</span></a></div>
      <p class="dataset-note">These {metric.row_count} disclosures name <strong>{_escape(recipient)}</strong> as recipient and classify the contributions as non-monetary support. Amounts are reported by the filer.</p>
      <div class="record-browser" data-record-browser>
        <aside class="record-filters" aria-label="Campaign record filters"><h3>Filter records</h3><label>Search<input type="search" data-record-filter placeholder="Recipient, date, or type"></label><label>Year<select data-record-field="year"><option value="">All years</option>{year_options}</select></label><label>Sort by<select data-record-sort><option value="newest">Date: newest first</option><option value="oldest">Date: oldest first</option><option value="high">Amount: highest first</option><option value="low">Amount: lowest first</option></select></label><button class="reset-button" type="button" data-record-reset>Clear filters</button></aside>
        <div class="record-results"><div class="results-heading"><h3>Contribution records</h3><p data-record-count aria-live="polite">Showing {metric.row_count} of {metric.row_count}</p></div>{_breakdown_table("Amount by year", years, metric.amount_cents)}<div class="table-scroll records-scroll"><table class="records-table"><thead><tr><th>Date</th><th>Recipient</th><th>Contribution type</th><th>Amount</th><th>Source</th></tr></thead><tbody>{rows}</tbody></table></div></div>
      </div>
    </section>"""


def _spending_browser(metric: Metric) -> str:
    records = [record for record in metric.records if isinstance(record, SpendingRecord)]
    rows = "".join(
        f"""<tr data-record-row data-year="{record.date[:4]}" data-department="{_escape(record.department.casefold())}" data-category="{_escape(record.object.casefold())}" data-date="{record.date}" data-amount="{record.amount_cents}" data-search="{_escape(f"{record.date} {record.department} {record.object}".casefold())}"><td>{record.date}</td><td>{_escape(record.department)}</td><td>{_escape(record.object)}</td><td class="money">{_escape(_money(record.amount_cents))}</td><td><a {_EXTERNAL_LINK_ATTRIBUTES} href="{_escape(_spending_row_url(metric, record))}" aria-label="Open official City row for document {_escape(record.document_id)}">City row <span aria-hidden="true">↗</span></a></td></tr>"""
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
    year_options = _filter_options({record.date[:4] for record in records})
    department_options = _filter_options({record.department for record in records})
    category_options = _filter_options({record.object for record in records})
    return f"""<section class="record-section" id="spending" aria-labelledby="spending-title">
      <div class="record-heading"><div><p class="section-label">Government spending</p><h2 id="spending-title">City payment lines</h2></div><a class="download-link" {_EXTERNAL_LINK_ATTRIBUTES} href="{_escape(_download_url(metric))}">Download CSV <span aria-hidden="true">↓</span></a></div>
      <p class="dataset-note">The City eCheckbook supplies departments and accounting categories but no descriptions for these lines. Amounts are individual payment lines, not contract totals.</p>
      <div class="record-browser" data-record-browser>
        <aside class="record-filters" aria-label="City payment filters"><h3>Filter records</h3><label>Search<input type="search" data-record-filter placeholder="Department, date, or category"></label><label>Year<select data-record-field="year"><option value="">All years</option>{year_options}</select></label><label>Department<select data-record-field="department"><option value="">All departments</option>{department_options}</select></label><label>Object category<select data-record-field="category"><option value="">All categories</option>{category_options}</select></label><label>Sort by<select data-record-sort><option value="newest">Date: newest first</option><option value="oldest">Date: oldest first</option><option value="high">Amount: highest first</option><option value="low">Amount: lowest first</option></select></label><button class="reset-button" type="button" data-record-reset>Clear filters</button></aside>
        <div class="record-results"><div class="results-heading"><h3>Payment records</h3><p data-record-count aria-live="polite">Showing {metric.row_count} of {metric.row_count}</p></div><div class="breakdown-grid">{_breakdown_table("By department", departments, metric.amount_cents)}{_breakdown_table("By object category", objects, metric.amount_cents)}{_breakdown_table("By year", years, metric.amount_cents)}</div><div class="table-scroll records-scroll"><table class="records-table"><thead><tr><th>Date</th><th>Department</th><th>Object category</th><th>Amount</th><th>Source</th></tr></thead><tbody>{rows}</tbody></table></div></div>
      </div>
    </section>"""


def _campaign_csv_url(campaign: CampaignProfile) -> str:
    parsed = urlparse(campaign.official_rows_url)
    return parsed._replace(path=parsed.path.removesuffix(".json") + ".csv").geturl()


def _campaign_page(
    campaign: CampaignProfile,
    publication: CampaignPublication,
    css_path: str,
    js_path: str,
) -> str:
    years = [(year.year, year.row_count, year.amount_cents) for year in campaign.by_year]
    donors = [(donor.name, donor.row_count, donor.amount_cents) for donor in campaign.top_donors]
    rows = "".join(
        f"""<tr data-record-row data-year="{record.date[:4]}" data-donor-type="{_escape(record.donor_type.casefold())}" data-correction="{"yes" if record.correction else "no"}" data-date="{record.date}" data-amount="{record.amount_cents}" data-search="{_escape(f"{record.date} {record.donor} {record.donor_type} {record.type}".casefold())}"><td>{record.date}</td><td>{_escape(record.donor)}</td><td>{_escape(record.donor_type.title())}</td><td>{_escape(record.type)}</td><td class="money">{_escape(_money(record.amount_cents))}</td><td>{"Correction" if record.correction else "Original filing"}</td><td><a {_EXTERNAL_LINK_ATTRIBUTES} href="{_escape(record.report_url)}" aria-label="Open official filing for transaction {_escape(record.transaction_id)}">Filing <span aria-hidden="true">↗</span></a></td></tr>"""
        for record in campaign.sample_records
    )
    year_options = _filter_options({record.date[:4] for record in campaign.sample_records})
    offices = _campaign_office(campaign)
    sample_count = len(campaign.sample_records)
    correction_note = (
        f"The City marks {campaign.correction_row_count:,} rows totaling "
        f"{_money(campaign.correction_amount_cents)} as corrections. They remain in the "
        "reported-row total because the public projection does not identify a reliable "
        "superseded row."
        if campaign.correction_row_count
        else "The City does not mark any rows in this profile as corrections."
    )
    body = f"""<main id="content">
      <nav class="breadcrumbs" aria-label="Breadcrumb"><a href="/">Data</a><span aria-hidden="true">/</span><a href="/#campaigns">Campaign finance</a><span aria-hidden="true">/</span><span aria-current="page">{_escape(campaign.name)}</span></nav>
      <section class="profile-intro campaign-intro" aria-labelledby="profile-title">
        <div class="profile-heading"><p class="section-label">{_escape(campaign.classification)}</p><h1 id="profile-title">{_escape(campaign.name)}</h1><p class="lede">Contributions reported to the City of Austin under this recipient name.</p><p class="profile-meta"><span>{_escape(publication.jurisdiction)}</span><span>{_escape(offices)}</span><span>Records through {_escape(_display_date(campaign.last_date))}</span></p></div>
        <div class="warning data-note" role="note"><strong>Reported data</strong><span>The records are self-reported to the City Clerk. {_escape(correction_note)}</span></div>
      </section>
      <nav class="section-nav" aria-label="On this page"><a href="#overview">Overview</a><a href="#contributors">Top contributors</a><a href="#records">Contribution records</a><a href="#sources">Sources and methods</a></nav>
      <section class="overview" id="overview" aria-labelledby="overview-title"><h2 id="overview-title">Overview</h2><dl class="summary-grid"><div><dt>Reported-row amount</dt><dd>{_escape(_money(campaign.amount_cents))}</dd><dd>{campaign.first_date[:4]}–{campaign.last_date[:4]}</dd></div><div><dt>Contribution rows</dt><dd>{campaign.row_count:,}</dd><dd>{campaign.correction_row_count:,} marked corrections</dd></div><div><dt>Reported donor names</dt><dd>{campaign.donor_count:,}</dd><dd>Exact names in the source</dd></div><div><dt>Office</dt><dd class="summary-text">{_escape(offices)}</dd><dd>From exact-matched City filer reports</dd></div></dl></section>
      <section class="record-section" id="contributors" aria-labelledby="contributors-title"><div class="record-heading"><div><p class="section-label">Full-snapshot summaries</p><h2 id="contributors-title">Top contributors and activity by year</h2></div></div><p class="dataset-note">Contributor rankings and yearly totals use all {campaign.row_count:,} published rows for this recipient, including rows marked as corrections.</p><div class="breakdown-grid campaign-breakdowns">{_breakdown_table("Top reported contributors", donors, campaign.amount_cents)}{_breakdown_table("Reported amount by year", years, campaign.amount_cents)}</div></section>
      <section class="record-section" id="records" aria-labelledby="records-title"><div class="record-heading"><div><p class="section-label">Row-level records</p><h2 id="records-title">Contribution records</h2></div><a class="download-link" {_EXTERNAL_LINK_ATTRIBUTES} href="{_escape(_campaign_csv_url(campaign))}">Download full City projection <span aria-hidden="true">↓</span></a></div><p class="dataset-note">Showing the {sample_count:,} most recent rows in this checked-in beta snapshot out of {campaign.row_count:,} total. Search and filters apply to the displayed rows; use the official projection for the complete set.</p><div class="record-browser" data-record-browser><aside class="record-filters" aria-label="Contribution record filters"><h3>Filter displayed rows</h3><label>Search<input type="search" data-record-filter placeholder="Donor, date, or type"></label><label>Year<select data-record-field="year"><option value="">All years</option>{year_options}</select></label><label>Donor type<select data-record-field="donorType"><option value="">All donor types</option><option value="individual">Individual</option><option value="entity">Entity</option></select></label><label>Filing status<select data-record-field="correction"><option value="">All filing statuses</option><option value="no">Original filing</option><option value="yes">Correction-marked</option></select></label><label>Sort by<select data-record-sort><option value="newest">Date: newest first</option><option value="oldest">Date: oldest first</option><option value="high">Amount: highest first</option><option value="low">Amount: lowest first</option></select></label><button class="reset-button" type="button" data-record-reset>Clear filters</button></aside><div class="record-results"><div class="results-heading"><h3>Displayed records</h3><p data-record-count aria-live="polite">Showing {sample_count} of {sample_count}</p></div><div class="table-scroll records-scroll"><table class="records-table campaign-records"><thead><tr><th>Date</th><th>Donor</th><th>Donor type</th><th>Contribution type</th><th>Amount</th><th>Filing status</th><th>Source</th></tr></thead><tbody>{rows}</tbody></table></div></div></div></section>
      <section class="methodology" id="sources" aria-labelledby="method-title"><p class="section-label">Documentation</p><h2 id="method-title">Sources and methods</h2><div class="method-grid"><div><h3>Recipient and office</h3><p>Rows are grouped only when recipient names become identical after capitalization, punctuation, and typography normalization. Office labels come from City campaign-report filer names matched by that same strict key. No fuzzy person matching is used.</p><p>Source names: {_escape(" · ".join(campaign.source_names))}</p></div><div><h3>Amounts and corrections</h3><p>Amounts are summed exactly as published. Correction-marked rows are labeled and counted separately but are not silently removed because the public contribution projection does not identify which prior row each correction replaces.</p><p>Snapshot through {_escape(_display_date(publication.snapshot_date))}.</p></div></div><div class="source-grid">{"".join(f'<article class="source-card"><h3>{_escape(source.title)}</h3><p>City of Austin dataset <code>{_escape(source.dataset_id)}</code></p><p><a {_EXTERNAL_LINK_ATTRIBUTES} href="{_escape(source.dataset_url)}">Dataset page <span aria-hidden="true">↗</span></a></p><details><summary>Snapshot fingerprint</summary><p><code>{_escape(source.artifact_sha256)}</code></p></details></article>' for source in publication.sources)}</div></section>
    </main>"""
    return _shell(
        title=f"{campaign.name} contributions — Money on Record",
        body=body,
        css_path=css_path,
        js_path=js_path,
    )


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
      <nav class="breadcrumbs" aria-label="Breadcrumb"><a href="/">Data</a><span aria-hidden="true">/</span><span>{_escape(profile.jurisdiction)}</span><span aria-hidden="true">/</span><span aria-current="page">{_escape(profile.name)}</span></nav>
      <section class="profile-intro" aria-labelledby="profile-title">
        <div class="profile-heading"><p class="section-label">Organization record</p>
        <h1 id="profile-title">{_escape(profile.name)}</h1>
        <p class="lede">{_escape(profile.summary)}</p>
        <p class="profile-meta"><span>{_escape(profile.jurisdiction)}</span><span>Records through {_escape(profile.snapshot_date)}</span></p></div>
        <div class="warning" role="note"><strong>{_escape(profile.identity.status)}</strong><span>{_escape(profile.identity.explanation)} {_escape(beta_notice)}</span></div>
      </section>
      <nav class="section-nav" aria-label="On this page"><a href="#overview">Overview</a><a href="#campaign">Campaign contributions</a><a href="#spending">Government payments</a><a href="#sources">Sources and methods</a></nav>
      <section class="overview" id="overview" aria-labelledby="overview-title">
        <h2 id="overview-title">Overview</h2>
        <dl class="summary-grid">
          <div><dt>Disclosed contribution amount</dt><dd>{_escape(_money(campaign.amount_cents))}</dd><dd>{campaign.row_count} disclosures · {_escape(_year_range(campaign))}</dd></div>
          <div><dt>Government payments</dt><dd>{_escape(_money(spending.amount_cents))}</dd><dd>{spending.row_count} lines · {_escape(_year_range(spending))}</dd></div>
          <div><dt>Campaign name</dt><dd>{_escape(profile.identity.campaign_name)}</dd><dd>City contribution disclosures</dd></div>
          <div><dt>Vendor name</dt><dd>{_escape(profile.identity.public_spending_name)}</dd><dd>City eCheckbook</dd></div>
        </dl>
      </section>
      {_campaign_browser(campaign)}
      {_spending_browser(spending)}
      <section class="methodology" id="sources" aria-labelledby="method-title">
        <p class="section-label">Documentation</p><h2 id="method-title">Sources and methods</h2>
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
  --navy: #122c3f;
  --navy-dark: #0a1d2a;
  --red: #b6342f;
  --blue: #176b8a;
  --ink: #20272b;
  --muted: #5c676e;
  --line: #cbd1d5;
  --soft-line: #e4e7e9;
  --paper: #ffffff;
  --wash: #f3f5f6;
  --warning: #fff6d8;
  --warning-line: #d29a18;
}

* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body { margin: 0; color: var(--ink); background: var(--paper); font: 16px/1.5 Arial, Helvetica, sans-serif; }
a { color: var(--blue); text-underline-offset: .16em; }
a:hover { color: var(--red); }
a:focus-visible, button:focus-visible, input:focus-visible, select:focus-visible, summary:focus-visible { outline: 3px solid #e0a51e; outline-offset: 2px; }
.skip-link { position: fixed; top: 8px; left: 8px; z-index: 20; padding: 9px 13px; color: white; background: var(--navy-dark); transform: translateY(-160%); }
.skip-link:focus { transform: none; }

.site-header { border-bottom: 5px solid var(--red); color: white; background: var(--navy); }
.nav-shell, main, .footer-shell { width: min(1640px, calc(100% - clamp(24px, 4vw, 64px))); margin-inline: auto; }
.nav-shell { min-height: 70px; display: flex; align-items: center; justify-content: space-between; gap: 24px; }
.brand { color: white; font: 700 1.38rem Georgia, "Times New Roman", serif; text-decoration: none; }
.brand:hover { color: white; }
.nav-shell nav { display: flex; align-items: center; gap: 22px; font-size: .84rem; }
.nav-shell nav a { color: white; font-weight: 700; }
.nav-shell nav span { padding-left: 22px; border-left: 1px solid rgb(255 255 255 / 35%); color: #d9e2e7; font-size: .68rem; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; }

main { padding-block: 38px 80px; }
.section-label { margin: 0 0 8px; color: var(--red); font-size: .72rem; font-weight: 800; letter-spacing: .09em; text-transform: uppercase; }
h1, h2, h3, p, dd, th, td { overflow-wrap: anywhere; }
h1 { max-width: 920px; margin: 5px 0 14px; font: 700 clamp(2.3rem, 5vw, 4rem)/1.02 Georgia, "Times New Roman", serif; letter-spacing: -.025em; }
h2 { margin: 0; font: 700 clamp(1.45rem, 2.5vw, 2rem)/1.15 Georgia, "Times New Roman", serif; }
h3 { margin: 0 0 10px; font-size: 1rem; }
.lede { max-width: 790px; margin: 0; color: var(--muted); font-size: 1.08rem; }
.home-intro { display: grid; grid-template-columns: minmax(560px, 800px) minmax(260px, 1fr); gap: clamp(48px, 7vw, 120px); align-items: end; padding: 34px 0 30px; }
.home-intro .database-meta { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); margin: 0 0 8px; padding-left: 28px; border-left: 3px solid var(--red); }
.home-intro .database-meta strong { grid-column: 1 / -1; margin-bottom: 8px; }
.home-intro .database-meta > * { padding: 0; }
.home-intro .database-meta > * + * { padding: 0; border: 0; }
.home-intro .database-meta span { color: var(--muted); }
.database-meta, .profile-meta { display: flex; flex-wrap: wrap; gap: 0; margin: 22px 0 0; color: var(--muted); font-size: .83rem; }
.database-meta > *, .profile-meta > * { padding-right: 14px; }
.database-meta > * + *, .profile-meta > * + * { padding-left: 14px; border-left: 1px solid var(--line); }
.database-meta strong { color: var(--ink); }

.directory { margin-top: 18px; }
.directory-search { display: grid; grid-template-columns: minmax(260px, .36fr) minmax(480px, .64fr); grid-template-rows: auto auto; column-gap: clamp(32px, 5vw, 80px); align-items: center; padding: 24px; color: white; background: var(--navy); }
.directory-search label { display: block; align-self: end; margin-bottom: 3px; font-size: .9rem; font-weight: 700; }
.directory-search > div { display: grid; grid-column: 2; grid-row: 1 / 3; grid-template-columns: 1fr auto; width: 100%; }
.directory-search input { min-width: 0; min-height: 48px; padding: 11px 13px; border: 0; border-radius: 0; font: inherit; }
.directory-search button { min-width: 112px; border: 0; color: white; background: var(--red); font-weight: 800; }
.directory-search p { align-self: start; margin: 3px 0 0; color: #d9e2e7; font-size: .78rem; }
.directory-heading, .record-heading, .results-heading { display: flex; align-items: end; justify-content: space-between; gap: 24px; }
.directory-heading { padding: 28px 0 12px; border-bottom: 2px solid var(--ink); }
.directory-heading p, .results-heading p { margin: 0; color: var(--muted); font-size: .82rem; }
.table-scroll { max-width: 100%; overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: .86rem; }
th, td { padding: 10px 9px; border-bottom: 1px solid var(--soft-line); text-align: left; vertical-align: top; }
thead th { color: #4f5b62; background: var(--wash); font-size: .68rem; letter-spacing: .055em; text-transform: uppercase; }
tbody th { font-weight: 700; }
tbody tr:hover { background: #f8fafb; }
.directory-table table { min-width: 820px; }
.directory-table th:first-child { width: 28%; }
.campaign-directory { max-height: 720px; overflow: auto; border-bottom: 1px solid var(--line); }
.campaign-directory table { min-width: 1120px; }
.campaign-directory thead { position: sticky; top: 0; z-index: 1; }
.campaign-directory th:first-child { width: 23%; }
.directory-action { text-align: right; white-space: nowrap; }
.table-status { display: block; margin-top: 4px; color: #7a5400; font-size: .68rem; font-weight: 400; text-transform: uppercase; }
.neutral-status { color: var(--muted); }
.numeric { font-variant-numeric: tabular-nums; }
.numeric strong, .numeric span { display: block; }
.numeric span { color: var(--muted); font-size: .75rem; }
.table-caption { max-width: 900px; margin: 11px 0 0; color: var(--muted); font-size: .78rem; }

.linked-records { margin-top: 58px; padding-top: 28px; border-top: 4px solid var(--navy); }
.section-heading { display: flex; align-items: end; justify-content: space-between; gap: 28px; }
.section-heading > p { margin: 0; color: var(--muted); font-size: .82rem; }
.section-intro { max-width: 820px; margin: 10px 0 18px; color: var(--muted); }

.coverage { display: grid; grid-template-columns: minmax(0, .8fr) minmax(0, 1.2fr); gap: 54px; margin-top: 58px; padding-top: 28px; border-top: 4px solid var(--navy); }
.coverage > div > p:last-child { color: var(--muted); }
.coverage dl { margin: 0; }
.coverage dl div { padding: 15px 0; border-bottom: 1px solid var(--line); }
.coverage dt { font-weight: 800; }
.coverage dd { margin: 3px 0 0; }
.coverage dd:last-child { color: var(--muted); font-size: .78rem; }

.breadcrumbs { display: flex; flex-wrap: wrap; gap: 8px; color: var(--muted); font-size: .78rem; }
.profile-intro { display: grid; grid-template-columns: minmax(560px, 1.1fr) minmax(390px, .9fr); gap: clamp(48px, 7vw, 110px); align-items: end; padding: 34px 0 32px; }
.profile-heading h1 { max-width: 800px; }
.warning { display: grid; grid-template-columns: 130px 1fr; gap: 18px; margin: 0 0 4px; padding: 16px; border-left: 4px solid var(--warning-line); background: var(--warning); font-size: .82rem; }
.warning strong { color: #694600; }
.section-nav { display: flex; flex-wrap: wrap; gap: 0; margin: 6px 0 34px; border-block: 1px solid var(--line); }
.section-nav a { padding: 11px 18px 11px 0; margin-right: 18px; font-size: .82rem; font-weight: 700; text-decoration: none; }
.overview { scroll-margin-top: 10px; }
.overview > h2 { padding-bottom: 10px; border-bottom: 2px solid var(--ink); }
.summary-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); margin: 0; border-bottom: 1px solid var(--line); }
.summary-grid div { min-width: 0; padding: 18px 16px 18px 0; }
.summary-grid div + div { padding-left: 16px; border-left: 1px solid var(--soft-line); }
.summary-grid dt { color: var(--muted); font-size: .7rem; font-weight: 800; letter-spacing: .05em; text-transform: uppercase; }
.summary-grid dd { margin: 5px 0 0; }
.summary-grid dd:first-of-type { font: 700 clamp(1.2rem, 2.2vw, 1.8rem)/1.12 Georgia, "Times New Roman", serif; }
.summary-grid dd:last-child { color: var(--muted); font-size: .76rem; }
.summary-grid dd.summary-text { font-size: clamp(1rem, 1.6vw, 1.35rem); }

.record-section, .methodology { scroll-margin-top: 10px; margin-top: 58px; padding-top: 22px; border-top: 5px solid var(--navy); }
.record-heading { padding-bottom: 12px; border-bottom: 1px solid var(--line); }
.download-link { font-size: .8rem; font-weight: 800; }
.dataset-note { max-width: 900px; margin: 14px 0 22px; color: var(--muted); font-size: .88rem; }
.record-browser { display: grid; grid-template-columns: 245px minmax(0, 1fr); gap: 32px; align-items: start; }
.record-filters { padding: 17px; border-top: 3px solid var(--red); background: var(--wash); }
.record-filters h3 { padding-bottom: 9px; border-bottom: 1px solid var(--line); }
.record-filters label { display: block; margin-top: 14px; color: #465159; font-size: .72rem; font-weight: 800; }
input, select { width: 100%; margin-top: 5px; padding: 9px 8px; border: 1px solid #aeb7bc; border-radius: 0; color: var(--ink); background: white; font: inherit; font-size: .82rem; }
.reset-button { width: 100%; margin-top: 17px; padding: 8px; border: 1px solid #89949a; color: var(--ink); background: white; font-weight: 700; }
.record-results { min-width: 0; }
.results-heading { padding: 0 0 9px; border-bottom: 2px solid var(--ink); }
.breakdown-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 24px; margin: 22px 0 26px; }
.breakdown { min-width: 0; margin: 20px 0 26px; }
.breakdown-grid .breakdown { margin: 0; }
.campaign-breakdowns { grid-template-columns: minmax(0, 1.35fr) minmax(340px, .65fr); }
.breakdown h3 { margin-bottom: 7px; }
.breakdown table { font-size: .78rem; }
.breakdown th, .breakdown td { padding: 7px 6px; }
.money { white-space: nowrap; text-align: right; font-variant-numeric: tabular-nums; }
.share { min-width: 112px; }
.share meter { width: 70px; height: 10px; vertical-align: middle; accent-color: var(--blue); }
.share span { margin-left: 5px; color: var(--muted); font-size: .68rem; }
.records-scroll { max-height: 660px; overflow: auto; border-block: 1px solid var(--line); }
.records-table { min-width: 760px; }
.campaign-records { min-width: 1040px; }
.records-table thead { position: sticky; top: 0; z-index: 1; }
.records-table tbody tr:nth-child(even) { background: #f8f9fa; }

.methodology > h2 { padding-bottom: 11px; border-bottom: 2px solid var(--ink); }
.method-grid, .source-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 28px; }
.method-grid { margin-top: 20px; }
.method-grid > div, .source-card { padding: 0; }
.method-grid p, .source-card p { color: var(--muted); font-size: .84rem; }
.source-grid { margin-top: 30px; padding-top: 22px; border-top: 1px solid var(--line); }
.source-card details { margin-top: 12px; }
.source-card summary { cursor: pointer; font-size: .8rem; }
.hashes { display: grid; gap: 4px; }
.hashes dt { margin-top: 6px; color: var(--muted); font-size: .7rem; }
.hashes dd { margin: 0; }
code { color: #33434c; font-size: .68rem; overflow-wrap: anywhere; }
[hidden] { display: none; }

.hero { padding-block: 54px; }
.hero .kicker { color: var(--red); font-size: .72rem; font-weight: 800; letter-spacing: .08em; text-transform: uppercase; }
.button { display: inline-block; margin-top: 20px; padding: 9px 13px; color: white; background: var(--red); font-weight: 700; text-decoration: none; }
.button:hover { color: white; background: #8e2521; }
.site-footer { border-top: 1px solid var(--line); color: var(--muted); background: var(--wash); font-size: .78rem; }
.footer-shell { display: grid; grid-template-columns: 1fr 1fr; gap: 32px; padding-block: 24px 36px; }
.footer-shell p { margin: 0; }

@media (max-width: 800px) {
  main { padding-top: 28px; }
  .coverage, .record-browser, .method-grid, .source-grid { grid-template-columns: 1fr; }
  .summary-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .summary-grid div:nth-child(3) { border-left: 0; }
  .record-filters { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
  .record-filters h3, .record-filters .reset-button { grid-column: 1 / -1; }
  .record-filters label, .record-filters .reset-button { margin-top: 0; }
  .campaign-breakdowns { grid-template-columns: 1fr; }
}

@media (max-width: 1050px) {
  .home-intro, .profile-intro { grid-template-columns: 1fr; gap: 26px; }
  .home-intro .database-meta { max-width: 560px; }
  .directory-search { grid-template-columns: 1fr; grid-template-rows: auto; gap: 9px; }
  .directory-search > div { grid-column: 1; grid-row: auto; }
  .directory-search p { margin-top: 0; }
}

@media (max-width: 1200px) and (min-width: 561px) {
  .breakdown-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .breakdown-grid .breakdown:last-child:nth-child(3) { grid-column: 1 / -1; }
}

@media (max-width: 560px) {
  .nav-shell nav a { display: none; }
  .nav-shell nav span { padding-left: 0; border: 0; }
  .database-meta > *, .profile-meta > * { width: 100%; padding: 0; }
  .database-meta > * + *, .profile-meta > * + * { padding: 0; border: 0; }
  .directory-search { padding: 18px; }
  .directory-search > div, .summary-grid, .breakdown-grid, .record-filters { grid-template-columns: 1fr; }
  .directory-search button { min-height: 44px; }
  .directory-table table { min-width: 0; }
  .campaign-directory { max-height: none; }
  .directory-table thead { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); clip-path: inset(50%); white-space: nowrap; }
  .directory-table tbody, .directory-table tr, .directory-table th, .directory-table td { display: block; width: 100%; }
  .directory-table th:first-child { width: 100%; }
  .directory-table tr { padding: 14px 0; border-bottom: 1px solid var(--line); }
  .directory-table th, .directory-table td { padding: 5px 9px; border: 0; }
  .directory-table td[data-label] { display: grid; grid-template-columns: minmax(118px, .8fr) minmax(0, 1fr); gap: 12px; }
  .directory-table td[data-label]::before { content: attr(data-label); grid-row: 1 / span 2; color: var(--muted); font-size: .68rem; font-weight: 800; letter-spacing: .04em; text-transform: uppercase; }
  .directory-table td[data-label] > strong, .directory-table td[data-label] > span { grid-column: 2; }
  .directory-action { margin-top: 5px; text-align: left; }
  .section-heading { display: block; }
  .section-heading > p { margin-top: 8px; }
  .warning { grid-template-columns: 1fr; }
  .summary-grid div + div { padding-left: 0; border-left: 0; border-top: 1px solid var(--soft-line); }
  .section-nav { display: block; padding-block: 6px; }
  .section-nav a { display: block; padding: 6px 0; }
  .footer-shell { grid-template-columns: 1fr; gap: 8px; }
}

@media (prefers-reduced-motion: reduce) { html { scroll-behavior: auto; } }
"""
SITE_JS = """const directoryFilter = document.querySelector('[data-directory-filter]');
const directoryRows = Array.from(document.querySelectorAll('[data-directory-row]'));
const directoryCount = document.querySelector('[data-directory-count]');

const updateDirectory = () => {
  if (!directoryFilter || !directoryCount) return;
  const query = directoryFilter.value.trim().toLocaleLowerCase();
  let visible = 0;
  directoryRows.forEach((row) => {
    row.hidden = !row.dataset.directorySearch.includes(query);
    visible += row.hidden ? 0 : 1;
  });
  directoryCount.textContent = `${visible} ${visible === 1 ? 'result' : 'results'}`;
};

directoryFilter?.addEventListener('input', updateDirectory);
document.querySelector('[data-directory-submit]')?.addEventListener('click', updateDirectory);

document.querySelectorAll('[data-record-browser]').forEach((browser) => {
  const filter = browser.querySelector('[data-record-filter]');
  const fieldFilters = Array.from(browser.querySelectorAll('[data-record-field]'));
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
      const fieldsMatch = fieldFilters.every((control) => {
        const selected = control.value;
        return !selected || row.dataset[control.dataset.recordField] === selected;
      });
      row.hidden = !row.dataset.search.includes(query) || !fieldsMatch;
      visible += row.hidden ? 0 : 1;
      body.append(row);
    });
    count.textContent = `Showing ${visible} of ${rows.length}`;
  };

  filter.addEventListener('input', update);
  fieldFilters.forEach((control) => control.addEventListener('change', update));
  sort.addEventListener('change', update);
  browser.querySelector('[data-record-reset]').addEventListener('click', () => {
    filter.value = '';
    fieldFilters.forEach((control) => { control.value = ''; });
    sort.value = 'newest';
    update();
  });
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
    for campaign in content.campaign_publication.campaigns:
        files[f"campaigns/{campaign.slug}/index.html"] = _campaign_page(
            campaign,
            content.campaign_publication,
            css_path,
            js_path,
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
            | {source.artifact_sha256 for source in content.campaign_publication.sources}
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
            {
                "schema_version",
                "content_sha256",
                "files",
                "profiles",
                "source_snapshots",
            },
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
