# Money on Record — L0

This repository contains the reproducible source-safety workspace and the first
browser-ready **Money on Record** static site. Local work does not require
Cloudflare or AWS credentials. Each environment's Terraform apply owns both
infrastructure and publication of the reviewed browser artifact.

The initial scope is six official City of Austin open-data sources:

- campaign report detail (`b2pc-2s8n`)
- campaign transaction detail (`g4yx-aw9r`)
- campaign contributions (`3kfv-biw6`)
- eCheckbook (`8c6z-qnmj`)
- contracts (`84ih-p28j`)
- purchase-order quantity and price (`3ebq-e9iz`)

## Local setup

With Nix and direnv:

```bash
direnv allow
uv sync --locked
```

Without Nix, install uv and let it provision the Python declared in
`.python-version`:

```bash
uv sync --locked
```

uv owns the project-local `.venv`; it does not need to be activated or managed
manually.

```bash
uv run mor-l0 inventory
uv run pytest
```

No app token is needed for occasional downloads, but Socrata rate limits are
friendlier when `AUSTIN_SOCRATA_APP_TOKEN` is set. Never commit that value.

## Static site

The reviewed, privacy-safe site inputs are [`site/content.json`](site/content.json)
and the narrow publication files in [`site/data/`](site/data/). The campaign
publication indexes all recipient totals from the frozen contribution snapshot,
retains the top twenty contributor aggregates, and includes at most the one
hundred most recent row-level records per recipient. Raw addresses, employer,
occupation, contact fields, and unrestricted source rows are not included.
Build the checked-in snapshot without network or cloud access:

```bash
uv run --locked mor-l0 build-site
uv run --locked mor-l0 verify-site \
  --archive build/money-on-record-site.zip \
  --expected-sha256 "$(cut -d ' ' -f 1 build/money-on-record-site.zip.sha256)"
```

The command creates `build/site/`, a byte-for-byte reproducible ZIP, and its
SHA-256 checksum. Generated files remain ignored; source content, builder code,
and tests are reviewed in pull requests. The archive contains rendered HTML,
content-hashed CSS and JavaScript, `robots.txt`, and a source-fingerprint
manifest—never unrestricted source downloads or candidate-review worksheets.

The environment's Terraform apply is the complete deployment. A UAT deployment
builds and verifies the exact current `main` artifact before AWS authentication;
Terraform then manages every rendered S3 object alongside the bucket and
CloudFront configuration. HTML and manifests revalidate, content-hashed assets
are immutable, and removing a generated path removes its state-owned object.
There is no separate upload workflow or post-apply publication step.

Production uses the same path but obtains `money-on-record-site-<version>.zip`
and its checksum from the selected immutable GitHub release. The release asset
is verified and extracted before the saved production plan is created, so that
single Terraform apply publishes the exact released files rather than
rebuilding them from a branch.

## Reproducible L0 workflow

```bash
# Freeze official metadata for all six datasets.
uv run mor-l0 freeze-metadata --all

# Download content-addressed CSV snapshots and write acquisition manifests.
uv run mor-l0 acquire --all

# Rehash every frozen response and compare byte counts and manifests.
uv run mor-l0 verify-artifacts

# Compute exact row/null/date/identity statistics from the acquired snapshots.
uv run mor-l0 profile --all

# Build the deterministic campaign publication from the latest acquired
# campaign-contribution and campaign-report snapshots.
uv run mor-l0 publish-campaigns

# Validate a public CSV projection with both a field allowlist and PII scanner.
uv run mor-l0 privacy-check path/to/public.csv --source campaign-contributions

# Audit allowlisted values in the private source snapshots without exporting them.
# A nonzero result identifies fields/rows that require narrowing before publication.
uv run mor-l0 privacy-audit --all

# Produce conservative organization-only candidates for manual review.
uv run mor-l0 candidates --limit 50

# Create and validate the ignored human-review worksheet.
uv run mor-l0 review-init
uv run mor-l0 review-validate
```

Raw responses are stored under `data/raw/<dataset-id>/<sha256>.csv`. Metadata is
stored the same way, and each network operation emits a JSON manifest containing
the requested URL, response headers, retrieval time, byte size, and SHA-256.
Those directories are ignored by Git; manifests can be archived separately if a
specific analytical release needs to be reconstructed.

Aggregate-only profile reports are safe to version and are written to
`reports/profiles/`; they cite the ignored raw artifact by content hash.
`publish-campaigns` writes the bounded, privacy-checked campaign input consumed
by the static site. It groups recipient and filer names only with the existing
typography-only strict key; it does not fuzzy-match people. Correction-marked
rows remain separately labeled because the City projection does not provide a
reliable key identifying the row each correction replaces.
After all candidates are adjudicated, `mor-l0 review-summary` emits a safe,
aggregate-only review report under `reports/reviews/`.

L0 deliberately does **not** do fuzzy person matching, infer household
relationships, or trust `MIS...` vendor codes as stable identities. See
[`docs/l0-acceptance.md`](docs/l0-acceptance.md) for the passed build gate and
the external validation that begins after this browser artifact is published.

Current results and the repo-ready handoff are in
[`docs/work-log.md`](docs/work-log.md) and
[`docs/repository-handoff.md`](docs/repository-handoff.md).
The AI-assisted candidate-review aggregate and its limitations are documented in
[`docs/l0-candidate-review-findings.md`](docs/l0-candidate-review-findings.md).
The complete human adjudication procedure is in
[`docs/manual-candidate-review.md`](docs/manual-candidate-review.md).

The development toolchain and proposed AWS/release lifecycle are documented in
[`docs/engineering/toolchain.md`](docs/engineering/toolchain.md) and
[`docs/engineering/delivery.md`](docs/engineering/delivery.md).
The AWS account and immutable GitHub OIDC bootstrap is in
[`docs/engineering/aws-bootstrap.md`](docs/engineering/aws-bootstrap.md).
