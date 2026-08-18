# Money on Record — L0

This directory is the repository-ready L0 workspace for **Money on Record**. It
does not deploy anything and does not require Cloudflare or AWS credentials.
Its purpose is to prove that the public sources are reproducible, safe to
publish, and dense enough to justify building a deployed organization-profile
beta. External usefulness is tested against that beta, not against this local
workspace.

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
After all candidates are adjudicated, `mor-l0 review-summary` emits a safe,
aggregate-only review report under `reports/reviews/`.

L0 deliberately does **not** do fuzzy person matching, infer household
relationships, or trust `MIS...` vendor codes as stable identities. See
[`docs/l0-acceptance.md`](docs/l0-acceptance.md) for the passed build gate and
the validation deliberately deferred until a browser-accessible beta exists.

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
