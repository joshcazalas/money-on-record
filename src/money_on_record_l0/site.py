# ruff: noqa: E501
from __future__ import annotations

import hashlib
import html
import json
import re
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import parse_qs, urlparse

from .privacy import contains_pii

SITE_SCHEMA_VERSION = 1
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
    if document["schema_version"] != SITE_SCHEMA_VERSION:
        raise SiteBuildError(f"site content schema must be {SITE_SCHEMA_VERSION}")
    beta_notice = _privacy_safe_text(document["beta_notice"], "beta_notice")
    raw_profiles = document["profiles"]
    if not isinstance(raw_profiles, list) or not raw_profiles:
        raise SiteBuildError("profiles must be a non-empty list")

    profiles: list[Profile] = []
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
            metrics.append(
                Metric(
                    kind=kind,
                    label=_privacy_safe_text(metric["label"], f"{metric_label}.label"),
                    amount_cents=_positive_int(
                        metric["amount_cents"], f"{metric_label}.amount_cents"
                    ),
                    row_count=_positive_int(metric["row_count"], f"{metric_label}.row_count"),
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
    return SiteContent(
        beta_notice=beta_notice,
        profiles=tuple(profiles),
        content_sha256=hashlib.sha256(raw).hexdigest(),
    )


def _escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def _money(cents: int) -> str:
    return f"${cents / 100:,.2f}"


def _shell(*, title: str, body: str, css_path: str) -> str:
    safe_title = _escape(title)
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="robots" content="noindex,nofollow,noarchive">
    <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'">
    <meta name="referrer" content="no-referrer">
    <title>{safe_title}</title>
    <link rel="stylesheet" href="/{_escape(css_path)}">
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
        <p><strong>Money on Record</strong> makes public campaign-finance and City spending records easier to inspect together.</p>
        <p>This beta does not allege influence, wrongdoing, or a verified shared identity.</p>
      </div>
    </footer>
  </body>
</html>
"""


def _index_page(content: SiteContent, css_path: str) -> str:
    profile_cards = []
    for profile in content.profiles:
        metrics = " · ".join(
            f"{_escape(metric.label)} {_escape(_money(metric.amount_cents))}"
            for metric in profile.metrics
        )
        profile_cards.append(
            f"""<article class="profile-card">
          <p class="status status-small">{_escape(profile.identity.status)}</p>
          <h2><a href="/profiles/{_escape(profile.slug)}/index.html">{_escape(profile.name)}</a></h2>
          <p>{_escape(profile.summary)}</p>
          <p class="profile-metrics">{metrics}</p>
          <a class="text-link" href="/profiles/{_escape(profile.slug)}/index.html">Inspect this profile <span aria-hidden="true">→</span></a>
        </article>"""
        )
    body = f"""<main id="content">
      <section class="hero home-hero" aria-labelledby="home-title">
        <p class="kicker">Campaign money and public spending, on record</p>
        <h1 id="home-title">Follow the records.<br>Keep the caveats.</h1>
        <p class="lede">Money on Record places carefully selected official records side by side without turning a name match into an accusation.</p>
        <div class="beta-callout" role="note">
          <strong>Research beta</strong>
          <span>{_escape(content.beta_notice)}</span>
        </div>
      </section>
      <section class="profiles" aria-labelledby="profiles-title">
        <div class="section-heading">
          <div>
            <p class="kicker">Available now</p>
            <h2 id="profiles-title">Organization profiles</h2>
          </div>
          <p>{len(content.profiles)} carefully scoped {"profile" if len(content.profiles) == 1 else "profiles"}</p>
        </div>
        <div class="profile-grid">
          {"".join(profile_cards)}
        </div>
      </section>
      <section class="method-grid" aria-labelledby="method-title">
        <div>
          <p class="kicker">How to read this beta</p>
          <h2 id="method-title">A trail to the source, not a verdict</h2>
        </div>
        <ol>
          <li><strong>See the totals.</strong> Each amount states exactly which rows it includes.</li>
          <li><strong>Open the official records.</strong> Every claim links to a narrow City projection.</li>
          <li><strong>Keep uncertainty visible.</strong> Cross-source identities remain unverified.</li>
        </ol>
      </section>
    </main>"""
    return _shell(title="Money on Record — research beta", body=body, css_path=css_path)


def _profile_page(profile: Profile, beta_notice: str, css_path: str) -> str:
    metric_cards = []
    source_cards = []
    for metric in profile.metrics:
        metric_cards.append(
            f"""<article class="metric-card">
          <p class="eyebrow">{_escape(metric.label)}</p>
          <p class="amount">{_escape(_money(metric.amount_cents))}</p>
          <p>{metric.row_count} {_escape(metric.row_description)}</p>
          <a class="text-link" {_EXTERNAL_LINK_ATTRIBUTES} href="{_escape(metric.official_rows_url)}">Inspect {metric.row_count} official City rows <span aria-hidden="true">↗</span></a>
        </article>"""
        )
        source_cards.append(
            f"""<article class="source-card">
          <h3>{_escape(metric.source_title)}</h3>
          <p>City of Austin dataset <code>{_escape(metric.dataset_id)}</code></p>
          <a {_EXTERNAL_LINK_ATTRIBUTES} href="{_escape(metric.dataset_url)}">Open the official dataset <span aria-hidden="true">↗</span></a>
          <details>
            <summary>Snapshot fingerprint</summary>
            <code>{_escape(metric.snapshot_sha256)}</code>
          </details>
        </article>"""
        )
    body = f"""<main id="content">
      <nav class="breadcrumbs" aria-label="Breadcrumb"><a href="/">Profiles</a><span aria-hidden="true">/</span><span aria-current="page">{_escape(profile.name)}</span></nav>
      <section class="hero profile-hero" aria-labelledby="profile-title">
        <p class="status">{_escape(profile.identity.status)}</p>
        <h1 id="profile-title">{_escape(profile.name)}</h1>
        <p class="lede">{_escape(profile.summary)}</p>
        <div class="warning" role="note">
          <strong>This identity link has not been verified.</strong>
          <span>{_escape(profile.identity.explanation)} {_escape(beta_notice)}</span>
        </div>
      </section>
      <section class="metric-grid" aria-label="Record totals">{"".join(metric_cards)}</section>
      <section class="panel identity-panel" aria-labelledby="identity-title">
        <div>
          <p class="kicker">Identity boundary</p>
          <h2 id="identity-title">Why these records are grouped</h2>
          <p>The matching rule uses organization records only. It does not use person matching, address matching, fuzzy similarity, or placeholder vendor codes.</p>
        </div>
        <dl class="fact-grid">
          <div><dt>Evidence</dt><dd>{_escape(profile.identity.evidence_tier)}</dd></div>
          <div><dt>Campaign name</dt><dd>{_escape(profile.identity.campaign_name)}</dd></div>
          <div><dt>City spending name</dt><dd>{_escape(profile.identity.public_spending_name)}</dd></div>
        </dl>
        <p class="boundary"><strong>What this does not show:</strong> This juxtaposition does not establish a quid pro quo, influence, wrongdoing, or even a verified shared legal identity.</p>
      </section>
      <section class="panel" aria-labelledby="sources-title">
        <div class="section-heading">
          <div><p class="kicker">Source and calculation trail</p><h2 id="sources-title">Check the underlying records</h2></div>
          <p>Complete City snapshots frozen {_escape(profile.snapshot_date)}</p>
        </div>
        <div class="source-grid">{"".join(source_cards)}</div>
        <p class="calculation"><strong>Calculation:</strong> Count the exact filtered rows and sum their named amount field. Money on Record does not proxy or republish unrestricted City responses.</p>
      </section>
    </main>"""
    return _shell(
        title=f"{profile.name} — Money on Record research beta", body=body, css_path=css_path
    )


def _not_found_page(css_path: str) -> str:
    body = """<main id="content">
      <section class="hero error-page" aria-labelledby="error-title">
        <p class="kicker">404 · Record not found</p>
        <h1 id="error-title">There is no profile at this address.</h1>
        <p class="lede">The beta publishes only a small reviewed set. The requested path may be old, incomplete, or intentionally unavailable.</p>
        <a class="button" href="/">Return to available profiles</a>
      </section>
    </main>"""
    return _shell(title="Not found — Money on Record", body=body, css_path=css_path)


SITE_CSS = """:root {
  color-scheme: light;
  --ink: #14231d;
  --muted: #5f6d65;
  --paper: #f5f1e7;
  --panel: #fffdf8;
  --line: #d4dbd6;
  --green: #145c41;
  --green-dark: #0b3c2a;
  --green-soft: #dcecdf;
  --amber: #7a5000;
  --amber-soft: #fff0c5;
  --blue: #2e5874;
  --shadow: 0 18px 50px rgb(23 47 36 / 8%);
}

* { box-sizing: border-box; }

html { scroll-behavior: smooth; }

body {
  margin: 0;
  color: var(--ink);
  background:
    radial-gradient(circle at 88% -8%, #d8eadf 0, transparent 34rem),
    var(--paper);
  font: 16px/1.6 Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}

a { color: var(--green); text-underline-offset: 0.2em; }
a:hover { color: var(--green-dark); }
a:focus-visible, summary:focus-visible { outline: 3px solid #c47e00; outline-offset: 4px; border-radius: 2px; }

.skip-link { position: fixed; top: 8px; left: 8px; z-index: 10; padding: 10px 14px; background: var(--ink); color: white; transform: translateY(-160%); }
.skip-link:focus { transform: none; }

.site-header { border-bottom: 1px solid var(--line); background: rgb(255 253 248 / 88%); }
.nav-shell, main, .footer-shell { width: min(1120px, calc(100% - 32px)); margin-inline: auto; }
.nav-shell { min-height: 72px; display: flex; align-items: center; justify-content: space-between; gap: 24px; }
.brand { color: var(--ink); font: 700 1.22rem Georgia, serif; letter-spacing: -0.015em; text-decoration: none; }
.brand span { color: var(--green); }
.environment { padding: 5px 9px; border: 1px solid var(--line); border-radius: 999px; color: var(--muted); font-size: 0.75rem; font-weight: 800; letter-spacing: 0.07em; text-transform: uppercase; }

main { padding-block: 44px 76px; }
.hero { padding-block: 36px 30px; }
.home-hero { max-width: 930px; padding-block: 76px 68px; }
.kicker, .eyebrow { margin: 0 0 10px; color: var(--blue); font-size: 0.78rem; font-weight: 800; letter-spacing: 0.09em; text-transform: uppercase; }
h1, h2, h3, p { overflow-wrap: anywhere; }
h1 { max-width: 920px; margin: 12px 0 18px; font: clamp(2.7rem, 8vw, 6.2rem)/0.94 Georgia, "Times New Roman", serif; letter-spacing: -0.055em; }
.profile-hero h1 { font-size: clamp(2.65rem, 7vw, 5rem); }
h2 { margin: 0; font: 700 clamp(1.55rem, 4vw, 2.25rem)/1.1 Georgia, serif; letter-spacing: -0.025em; }
h3 { margin: 0 0 8px; font-size: 1rem; }
.lede { max-width: 770px; margin: 0; color: var(--muted); font-size: clamp(1.02rem, 2.4vw, 1.2rem); }

.beta-callout, .warning { display: grid; grid-template-columns: max-content 1fr; gap: 14px 22px; max-width: 900px; margin-top: 30px; padding: 18px 20px; border-left: 5px solid #c78b18; background: #fff8e7; }
.beta-callout strong, .warning strong { color: var(--amber); }
.status { display: inline-flex; width: fit-content; margin: 0; padding: 7px 11px; border: 1px solid #dfb95e; border-radius: 999px; color: var(--amber); background: var(--amber-soft); font-size: 0.76rem; font-weight: 800; letter-spacing: 0.06em; text-transform: uppercase; }
.status-small { padding: 4px 8px; font-size: 0.68rem; }

.profiles, .method-grid, .panel { margin-top: 24px; }
.section-heading { display: flex; align-items: end; justify-content: space-between; gap: 28px; margin-bottom: 22px; }
.section-heading > p { max-width: 360px; margin: 0; color: var(--muted); text-align: right; }
.profile-grid, .metric-grid, .source-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; }
.profile-card, .metric-card, .source-card, .panel { border: 1px solid var(--line); border-radius: 16px; background: var(--panel); box-shadow: var(--shadow); }
.profile-card, .metric-card, .source-card { padding: 26px; }
.profile-card h2 { margin: 18px 0 10px; }
.profile-card h2 a { color: var(--ink); }
.profile-card > p:not(.status) { color: var(--muted); }
.profile-metrics { padding-top: 14px; border-top: 1px solid var(--line); font-size: 0.86rem; }
.text-link { display: inline-block; margin-top: 8px; font-weight: 750; }

.method-grid { display: grid; grid-template-columns: 0.9fr 1.1fr; gap: 48px; padding-block: 48px; border-top: 1px solid var(--line); }
.method-grid ol { display: grid; gap: 18px; margin: 0; padding-left: 1.3rem; }
.method-grid li { padding-left: 8px; }

.breadcrumbs { display: flex; gap: 10px; align-items: center; color: var(--muted); font-size: 0.87rem; }
.metric-grid { margin-top: 8px; }
.metric-card .amount { margin: 7px 0 5px; font: 700 clamp(2.3rem, 6vw, 3.7rem)/1 Georgia, serif; letter-spacing: -0.045em; }
.metric-card > p:not(.eyebrow, .amount) { min-height: 3.2em; color: var(--muted); }
.panel { padding: clamp(24px, 5vw, 40px); }
.identity-panel { display: grid; grid-template-columns: 0.85fr 1.15fr; gap: 34px 48px; }
.identity-panel > div:first-child p:last-child { color: var(--muted); }
.fact-grid { display: grid; gap: 0; margin: 0; }
.fact-grid div { padding: 14px 0; border-top: 1px solid var(--line); }
.fact-grid dt { color: var(--muted); font-size: 0.78rem; }
.fact-grid dd { margin: 2px 0 0; font-weight: 700; }
.boundary { grid-column: 1 / -1; margin: 0; padding: 18px 20px; border-radius: 12px; background: var(--green-soft); }
.source-card { box-shadow: none; }
.source-card p { color: var(--muted); }
.source-card details { margin-top: 18px; }
.source-card summary { cursor: pointer; color: var(--muted); font-size: 0.84rem; }
code { color: #33473d; font-size: 0.76rem; overflow-wrap: anywhere; }
.calculation { margin: 24px 0 0; color: var(--muted); }

.error-page { min-height: 55vh; display: flex; flex-direction: column; justify-content: center; }
.error-page h1 { font-size: clamp(2.5rem, 7vw, 5rem); }
.button { width: fit-content; margin-top: 28px; padding: 12px 17px; border-radius: 8px; color: white; background: var(--green); font-weight: 750; text-decoration: none; }
.button:hover { color: white; background: var(--green-dark); }

.site-footer { border-top: 1px solid var(--line); color: var(--muted); font-size: 0.86rem; }
.footer-shell { display: grid; grid-template-columns: 1fr 1fr; gap: 32px; padding-block: 28px 42px; }
.footer-shell p { margin: 0; }

@media (max-width: 760px) {
  main { padding-top: 28px; }
  .home-hero { padding-block: 48px; }
  .profile-grid, .metric-grid, .source-grid, .identity-panel, .method-grid { grid-template-columns: 1fr; }
  .beta-callout, .warning { grid-template-columns: 1fr; }
  .section-heading { display: block; }
  .section-heading > p { margin-top: 10px; text-align: left; }
  .footer-shell { grid-template-columns: 1fr; gap: 10px; }
}

@media (prefers-reduced-motion: reduce) {
  html { scroll-behavior: auto; }
}
"""


def _write_site(output: Path, content: SiteContent) -> dict[str, bytes]:
    css_bytes = SITE_CSS.encode("utf-8")
    css_digest = hashlib.sha256(css_bytes).hexdigest()[:16]
    css_path = f"assets/site-{css_digest}.css"
    files: dict[str, bytes] = {
        css_path: css_bytes,
        "index.html": _index_page(content, css_path).encode("utf-8"),
        "404.html": _not_found_page(css_path).encode("utf-8"),
        "robots.txt": b"User-agent: *\nDisallow: /\n",
    }
    for profile in content.profiles:
        files[f"profiles/{profile.slug}/index.html"] = _profile_page(
            profile, content.beta_notice, css_path
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
