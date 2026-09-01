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
direct contact and street-address fields are never public product fields. L0
cross-domain matching is further limited to records explicitly typed as entities;
there is no person matching or inference from name shape.

A scanner pass is a guardrail, not proof. Before launch, a hostile human review
must inspect the public schema, samples, URLs, free-text fields, downloadable
files, and error/log payloads. Scanner output, build logs, errors, analytics,
traces, and PR comments must never repeat even a partial matched value or raw
source row.

The AI-assisted L0 review and production requirements are recorded in
[`analysis/hostile-privacy-review.md`](analysis/hostile-privacy-review.md).
