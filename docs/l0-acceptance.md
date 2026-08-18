# L0 build acceptance and deployed-beta validation

L0 now separates two questions that require different evidence:

1. **Build gate:** Is the source, privacy, and identity evidence strong enough to
   justify implementing and deploying a serious beta?
2. **Validation gate:** Once a nontechnical user can visit that beta, is the
   product understandable and useful enough to promote or continue?

Requiring external audience feedback before a stable browser-accessible product
exists would make recruitment harder and produce feedback about setup and
incompleteness instead of the product. External validation therefore does not
block product or AWS implementation.

## Build gate — passed August 18, 2026

- [x] Versioned contracts name all six v1 sources and distinguish canonical,
  official-projection, and current-only roles.
- [x] Acquisition is content-addressed and emits URL, timestamp, response
  headers, byte length, and SHA-256 manifests.
- [x] Public schemas use explicit allowlists; unknown columns fail closed.
- [x] A second scanner rejects common direct-contact PII patterns in allowed
  text fields.
- [x] Name normalization is deterministic, tested, and organization-only.
- [x] `MIS...` vendor codes are excluded from cross-domain identity evidence.
- [x] Freeze current metadata and reconcile every configured field to it.
- [x] Acquire and exactly profile every complete v1 source snapshot.
- [x] Generate value-free fixtures from every source and commit only fixtures
  that pass the privacy check.
- [x] Complete and validate an explicitly AI-assisted review of all 41
  conservative organization candidates; commit only its aggregate summary and
  keep every beta identity visibly unverified pending human audit.
- [x] Every displayed aggregate in the mock profile links to the exact source
  rows used to calculate it.
- [x] Complete an AI-assisted hostile review of the prototype, schemas, exact
  projections, URLs, candidate names, and scanner/log behavior; remediate the
  identified implementation risks.
- [x] Record Josh's explicit human acceptance of the hostile-review gate and
  carry its production controls into product/deployment work.
- [x] Record the decision to proceed with a deployed beta without claiming that
  external usefulness or candidate identity has already been validated.

## Deployed-beta validation gate — intentionally deferred

Tracked in
[#14](https://github.com/joshcazalas/money-on-record/issues/14). Before broad
promotion or describing Money on Record as externally validated:

- [ ] Deploy a stable, navigable beta that requires no GitHub or local setup.
- [ ] Test representative profiles with at least one reporter,
  campaign-finance researcher, civic-data user, or comparably relevant
  public-records user; record what was and was not useful.
- [ ] Human-audit every Tier B identity displayed in the beta and a strict-tier
  sample before changing any identity from `unverified` to `verified`.
- [ ] Send or explicitly disposition City data-owner questions that affect the
  semantics displayed by the beta.
- [ ] Record the post-beta continue, pivot, or stop decision.

## Build decision

**PASS TO BUILD A DEPLOYED BETA.** All six datasets can be replayed, the exact
prototype projection passed hostile privacy review, and 41 conservative
candidate relationships survived the AI-assisted evidence pass without person
matching. This decision authorizes product and infrastructure work; it is not a
claim of product-market validation or verified shared identity.

The beta must preserve unverified-match language, exact source lineage,
page-level privacy scans, and the production controls in
[`analysis/hostile-privacy-review.md`](analysis/hostile-privacy-review.md).

## Kill or pivot decision

If deployed profiles remain confusing, unused, or sparse after conservative
matching, narrow the product to source-specific exploration or stop. Do not
compensate by fuzzy-matching people, trusting placeholder vendor IDs, exposing
raw address/contact columns, or presenting ambiguous organizations as verified
matches.
