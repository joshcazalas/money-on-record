# Repository handoff

The project lives at `/home/joshcaz/develop/money-on-record` and on GitHub at
[`joshcazalas/money-on-record`](https://github.com/joshcazalas/money-on-record).
The protected `main` branch, required CI checks, release-impact labels, and
merge-only repository settings are configured. No Cloudflare or AWS resources
have been created.

`data/raw/`, `data/derived/`, local profile runs, the uv environment, and staging
files are ignored. Frozen metadata, acquisition manifests, field dictionaries,
aggregate profiles, synthetic fixtures, source code, tests, and the static
prototype are versioned.

## Rebuild or continue locally

```bash
uv sync --locked
uv run pytest
uv run mor-l0 inventory
uv run mor-l0 candidates --limit 50
uv run mor-l0 review-init
uv run mor-l0 review-validate
uv run mor-l0 identity-audit
uv run mor-l0 privacy-audit --all
```

The six raw snapshots are already present on this machine. Re-running `acquire`
makes a fresh network observation and content-addresses it; an unchanged response
reuses the existing hash rather than duplicating the artifact. `review-init`
refuses to overwrite an existing worksheet.

## Next work, in order

1. Complete issue #1: record the first deployable architecture and define its
   thinnest end-to-end product slice.
2. Complete issue #2: bootstrap the AWS organization/accounts, Terraform state,
   and repository-bound GitHub OIDC roles without long-lived access keys.
3. Implement and deploy a representative static-first beta while carrying all
   hostile-review production controls forward.
4. Configure `moneyonrecord.org` only when the beta is ready for a stable
   browser URL.
5. Run issue #14 against the deployed beta: external usability, focused human
   identity audit, and City questions tied to displayed semantics.
6. Revise the product from that evidence and record the post-beta
   continue/pivot/stop decision.

## Hosting direction for the beta

The current evidence favors a static-first product: precompute narrow,
scanner-passing public projections whose identity links remain unverified,
publish a static web build to private S3, and serve it through CloudFront. Add
Lambda only for interactions that cannot be expressed as static artifacts or
client-side indexes. The 711 MB eCheckbook CSV is a bulk ingestion job and
should run on the home server or a scheduled container, not in a Lambda request
path.

That shape preserves the career-relevant AWS surface while allowing the idle
portfolio site to remain very cheap. DNS and Cloudflare configuration remain
deliberately deferred.
