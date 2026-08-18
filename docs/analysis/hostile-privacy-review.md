# AI-assisted hostile privacy review

Review date: August 18, 2026

## Decision

The current local organization-profile prototype is suitable for the external
L0 usability test after the remediations in this review. It is **not approved
for production publication**. Josh's human sign-off, the external usability
test, City data-owner answers, and production response/logging controls remain
open gates.

The exact prototype projections were checked against the frozen source
artifacts: 53 campaign-contribution rows and 208 eCheckbook rows produced zero
PII-pattern findings across their allowlisted values. No source values or
matched fragments were printed, committed, or added to logs.

## Scope

The review treated the following as public surface, including indirect paths:

- configured public and restricted fields for all six sources;
- the exact rows, labels, IDs, hashes, and outbound URLs in the static profile;
- organization-candidate admission rules;
- CSV headers, malformed rows, free text, and scanner output;
- accidental indexing, browser referrers, and basic static-page policy;
- future downloads, errors, logs, and official-source handoffs.

The raw artifacts reviewed locally are the content-addressed snapshots already
named in their acquisition manifests. They remain ignored private inputs.

## Findings and disposition

### Exact source links returned more than the page allowed

**Severity: high — remediated.** The prototype and generated candidate evidence
URLs filtered the right official rows but omitted Socrata's `$select`. A click
could therefore return every source column, including columns Money on Record
classifies as restricted.

Generated evidence URLs now select only the source contract's allowlisted
fields and reject filters on non-public fields. Both prototype API links also
carry an explicit allowlisted `$select`. Tests hold that boundary in place.

### Broad source projections contain contact/address-shaped prose

**Severity: high for bulk publication — blocked by policy and scanner.** A full
local scan of allowlisted values found:

| Source | Result | Fields requiring review |
| --- | ---: | --- |
| campaign reports | 0 findings | none |
| campaign contributions | 0 findings | none |
| campaign transactions | 3 findings | `expense_description` |
| eCheckbook | at least 25 findings before the configured cap | administrative/name fields, including `div_nm`, `gp_nm`, and `lgl_nm` |
| contracts | 1 finding | `doc_dscr` |
| purchase orders | at least 25 findings before the configured cap | primarily `extended_description`; also `contract_name` and a commodity-shaped value |

The scanner is deliberately conservative: an address-shaped administrative or
organization name is a review finding, not proof that the value identifies a
person. The result still means the broad source allowlists are ceilings, not
ready-made downloadable schemas. A filtered projection must pass the scanner
after its rows and fields are selected. A failing projection must be narrowed,
redacted through an explicitly reviewed transformation, or withheld; it must
never be published merely because the City published the source value.

The repeatable `mor-l0 privacy-audit` command scans these private source
artifacts in place without exporting values. A nonzero result is expected while
broad fields contain review findings.

### Address- or contact-shaped values could enter organization candidates

**Severity: medium — remediated.** Vendor legal-name columns sometimes contain
address-shaped values. Candidate generation now rejects PII-shaped campaign and
public-record names before normalization or cross-domain matching. The existing
explicit entity-type and placeholder-code gates still apply.

### Scanner bypasses and scanner logs

**Severity: medium — remediated.** Compact phone formats, space-delimited SSN
shapes, P.O. boxes, and CSV rows with undeclared trailing cells could evade the
old checks. Those cases now fail. Digit-only structured IDs are distinguished
from prose to avoid treating City document and vendor identifiers as phone
numbers. Findings always log `[redacted]`; even partial matched values are no
longer echoed.

### Prototype browser behavior

**Severity: medium — remediated for the local artifact.** The prototype now
requests `noindex,nofollow,noarchive`, applies a restrictive meta CSP suitable
for its script-free content, and suppresses referrers on every outbound link.
These controls reduce harm if the explicitly local artifact is accidentally
served, but they do not turn it into a production page.

## Production requirements carried forward

- Build the final page from a narrower page-level schema; never serialize a
  source contract's entire allowlist by default.
- Run the privacy check on every generated public artifact after filtering and
  before upload. Do not upload on findings or malformed rows.
- Escape all source text for its HTML/JSON context and add hostile strings to
  renderer tests before introducing generated pages.
- Emit no raw row, query response, contact value, or scanner match in errors,
  analytics, traces, Terraform output, build logs, or PR comments.
- Do not proxy or cache unrestricted City responses. Outbound links must be
  visibly labeled as official City pages that follow the City's publication
  policy, not Money on Record's narrower policy.
- Configure CloudFront response headers for CSP (including
  `frame-ancestors 'none'`), `Referrer-Policy: no-referrer`,
  `X-Content-Type-Options: nosniff`, and a minimal `Permissions-Policy`.
- Keep public storage private behind CloudFront and prevent directory-style
  listing or publication of raw, derived-review, and diagnostic artifacts.
- Repeat this review when page fields, source contracts, matching rules,
  downloads, analytics, logging, or hosting behavior changes.

## Human sign-off checklist

Before marking the hostile-review gate complete, Josh should confirm in this
PR that:

- the two exact profile projections are an acceptable public minimum;
- broad source fields with findings will remain blocked from bulk publication;
- outbound official-source links are acceptable with `$select`, no-referrer,
  and clear source labeling; and
- the production requirements above carry into the product/deployment work.
