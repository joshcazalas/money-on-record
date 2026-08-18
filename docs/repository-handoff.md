# Repository handoff

The project now lives in the cloned Git repository at
`/home/joshcaz/develop/money-on-record`, with
`git@github.com:joshcazalas/money-on-record.git` configured as `origin`. No
Cloudflare or AWS resources were created during L0 staging.

The remote is empty and `main` has no commits yet. Review the initial staged set
before creating and pushing the first commit:

```bash
cd /home/joshcaz/develop/money-on-record
git add .
git status --short
```

`data/raw/`, `data/derived/`, old local profile runs, the virtual environment,
and staging files are ignored.
Frozen metadata, acquisition manifests, field dictionaries, aggregate profiles,
synthetic fixtures, source code, tests, and the static prototype are intended to
be versioned.

## Rebuild or continue locally

```bash
uv sync --extra dev
uv run pytest
uv run mor-l0 inventory
uv run mor-l0 candidates --limit 50
uv run mor-l0 identity-audit
```

The six raw snapshots are already present on this machine. Re-running `acquire`
makes a fresh network observation and content-addresses it; an unchanged response
reuses the existing hash rather than duplicating the artifact.

## Next work, in order

1. Adjudicate 25–50 rows in
   `data/derived/l0-organization-candidates.csv`, keeping rejections and uncertain
   cases as resolver regression examples.
2. Run the five-task static-profile test with a reporter or civic-data user and
   record results in `docs/mock-profile-test.md`.
3. Send the documented questions to the relevant City data owners, especially
   the malformed board-award years, `MIS` code semantics, report/transaction key
   behavior, and contracts history.
4. Revise the profile and match policy from that evidence, then make the formal
   L0 pass/pivot decision.
5. Only after the gate passes, scaffold product and deployment code.

## Hosting direction after L0

The current evidence favors a static-first product: precompute reviewed public
projections, publish a static web build to private S3, and serve it through
CloudFront. Add Lambda only for interactions that cannot be expressed as static
artifacts or client-side indexes. The 711 MB eCheckbook CSV is a bulk ingestion
job and should run on the home server or a scheduled container, not in a Lambda
request path.

That shape preserves the career-relevant AWS surface while allowing the idle
portfolio site to remain very cheap. DNS and Cloudflare configuration remain
deliberately deferred.
