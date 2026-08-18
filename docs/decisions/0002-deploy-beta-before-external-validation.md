# 0002 — Deploy a credible beta before external audience validation

Status: accepted on August 18, 2026

## Context

The local L0 work proves reproducibility, conservative organization matching,
exact source lineage, and a viable privacy boundary. It does not provide a
credible artifact for a busy reporter, campaign-finance researcher, or
civic-data user: the prototype is a local HTML file inside a partial GitHub
project, and Josh has no existing relationships with those audiences.

Cold outreach at this stage would ask a nontechnical stranger to invest time in
setup and hypotheticals while offering little evidence that the project will be
maintained. Feedback would be biased toward prototype incompleteness rather than
the actual product.

## Decision

Pass the technical build gate and implement a stable, browser-accessible beta
before recruiting external participants. External usability, focused human
identity verification, and City data-owner outreach move to the deployed-beta
validation issue (#14); they do not block product code, AWS bootstrap, or the
first deployment.

The beta must:

- preserve visible beta and unverified-match language;
- carry forward the accepted hostile-privacy production controls;
- provide representative profiles and exact official-source links without
  requiring GitHub or local setup; and
- avoid claiming external validation, verified identity, influence, or
  wrongdoing.

## Consequences

This sequence spends some implementation effort before audience validation,
but it makes the eventual request concrete, respectful, and much more likely to
produce useful feedback. Static-first S3 and CloudFront keep that bet small and
career-relevant. If the deployed beta still fails to attract useful feedback or
profiles are not valuable, the project can pivot or stop without weakening its
privacy and source-integrity rules.
