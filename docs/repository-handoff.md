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

1. Audit the completed AI-assisted review using the ignored local
   `data/derived/l0-ai-review-audit.md`: inspect every Tier B identity and the
   proposed strict-tier sample.
2. Correct any disputed worksheet rows, rerun validation and
   `mor-l0 review-summary --provenance AI_ASSISTED`, then decide whether the
   human-audit gate can be accepted.
3. Review and sign off on `analysis/hostile-privacy-review.md`; the AI-assisted
   review and implementation remediations are complete, but the human gate is
   deliberately still open.
4. Run the five-task static-profile test with a reporter or civic-data user and
   record results in `mock-profile-test.md`.
5. Send the documented questions to the relevant City data owners, especially
   the malformed board-award years, `MIS` code semantics, report/transaction key
   behavior, and contract history.
6. Revise the profile and match policy from that evidence, then make the formal
   L0 pass/pivot decision.
7. Only after the gate passes, scaffold product and deployment code.

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
