# Public data boundary

The City publishing a value does not automatically make it appropriate for this
product to republish. Money on Record minimizes the public surface to the fields
needed to explain campaign money and public spending.

The pipeline is default-deny:

1. Raw official artifacts stay in ignored local storage.
2. Each source contract lists the only columns eligible for a public projection.
3. Any new or renamed column fails schema validation until explicitly reviewed.
4. Allowed text is scanned for email addresses, phone numbers, Social Security
   number shapes, and street-address shapes.
5. Generated development fixtures retain headers and null patterns but replace
   every non-null source value with deterministic synthetic data.

The source allowlist is a maximum eligibility boundary, not a page or download
schema. Each public artifact must choose the smallest fields and rows needed for
its claim, then pass the scanner after that selection. Exact-row Socrata links
must include an allowlisted `$select`; a `$where` alone is not a privacy
boundary. Official dataset or filing links leave Money on Record and must be
labeled as such. A small, field-minimized, human-reviewed projection may be
versioned and rendered by the product when it is necessary to inspect the claim;
unrestricted source responses and unreviewed fields must not be cached or
republished.

Names involved in a public transaction may be necessary factual content, but
direct contact, street-address, employer, and occupation fields are never public
product fields. Campaign recipient pages group source names only with the
typography-only strict key and may display the donor name, donor type, amount,
date, contribution type, correction marker, and official filing link. They do
not join individual donors to any other dataset or infer that similarly named
people are the same person. Cross-domain organization matching remains limited
to records explicitly typed as entities.

The checked-in campaign publication is bounded rather than a source mirror. It
contains full-snapshot recipient/year/top-contributor aggregates and no more
than the one hundred most recent row-level records per recipient. The complete
filtered record set remains an outbound link to the City's official projection.
Rows the City marks as corrections remain labeled; Money on Record does not
silently discard or replace a row without a reliable public supersession key.

A scanner pass is a guardrail, not proof. Before launch, a hostile human review
must inspect the public schema, samples, URLs, free-text fields, downloadable
files, and error/log payloads. Scanner output, build logs, errors, analytics,
traces, and PR comments must never repeat even a partial matched value or raw
source row.

The AI-assisted L0 review and production requirements are recorded in
[`analysis/hostile-privacy-review.md`](analysis/hostile-privacy-review.md).
