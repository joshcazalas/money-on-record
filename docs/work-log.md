# L0 work log — August 18, 2026

## Completed

- Defined six versioned official-source contracts with canonical,
  official-projection, and current-only roles.
- Froze Socrata metadata and generated default-deny field dictionaries from the
  live API schema.
- Downloaded complete, content-addressed CSV snapshots with SHA-256 acquisition
  manifests.
- Produced exact row/null/distinct/date/candidate-key profiles for all sources.
- Added chronological date parsing and suspicious-year detection.
- Added an allowlist-based public boundary and second-pass direct-contact PII
  scanner; six value-free fixtures pass it.
- Added deterministic organization-only normalization and legal-suffix candidate
  tiers; person matching and fuzzy matching are absent by design.
- Measured and excluded all `MIS...` vendor-code records from identity evidence.
- Generated a 41-row, source-linked review set from only contribution rows typed
  `ENTITY`.
- Added a fingerprinted local review worksheet, controlled decisions and
  reasons, candidate-drift detection, and a privacy-safe aggregate report
  contract.
- Completed and validated an AI-assisted evidence review of all 41 candidate
  relationships: 41 `YES`, 0 `NO`, and 0 `UNCERTAIN`. The aggregate declares
  AI provenance; focused human audit remains pending.
- Built a local, unverified static profile and verified its counts and totals
  against the official source filters.
- Completed an AI-assisted hostile privacy review, scanned the exact 53-row and
  208-row prototype projections with zero findings, constrained exact-row links
  to allowlisted fields, and hardened candidate admission, scanner output, CSV
  parsing, and local prototype browser behavior.
- Recorded Josh's explicit acceptance of the hostile privacy gate.
- Passed the technical build gate and deferred external usability, human
  identity verification, and semantic outreach until a stable deployed beta
  gives participants something credible and usable to evaluate.
- Added executable tests, linting, L0 gates, City questions, manual-review rules,
  and an external usability-test script.

## Deferred deployed-beta validation

- Human identity verification: audit displayed Tier B rows and a strict-tier
  sample before changing any beta identity from unverified to verified.
- External profile test: run against a stable browser-accessible beta, not the
  repository or local prototype.
- City data-owner questions: send or disposition questions affecting displayed
  semantics once the beta makes the requested context concrete.
- Post-beta validation decision: continue, pivot, or stop based on observed use
  and audience feedback.

These items are tracked in GitHub issue #14 and do not block product or AWS
implementation.

## Important findings

- All six complete exports met the expected density threshold and reconciled to
  the configured schema.
- Only 709 of 120,849 contribution rows are explicitly typed as entities. They
  represent 247 strict normalized organization keys.
- The conservative resolver found 41 review candidates across 31 campaign entity
  keys—enough to continue L0 without weakening identity rules.
- All 28 strict-name and 13 narrow legal-suffix candidates survived the
  AI-assisted first pass. This supports high precision in the deliberately
  conservative sample but does not measure resolver recall.
- Excluding `MIS...` values removes 229,610 eCheckbook rows spanning 73,709 raw
  names and 23 placeholder codes.
- One campaign election date is in 2104; 563 contract board-award dates use years
  between `0010` and `0023`.
- Campaign transaction IDs are unique. Campaign report IDs are not row keys.
