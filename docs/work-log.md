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
- Built a local, unverified static profile and verified its counts and totals
  against the official source filters.
- Added executable tests, linting, L0 gates, City questions, manual-review rules,
  and an external usability-test script.

## Open gates

- Candidate review: 0 of 41 adjudicated.
- External profile test: not yet performed.
- City data-owner questions: not yet sent or answered.
- Hostile human review of the proposed public schema: not yet performed.
- Formal L0 pass/pivot decision: pending the above evidence.

## Important findings

- All six complete exports met the expected density threshold and reconciled to
  the configured schema.
- Only 709 of 120,849 contribution rows are explicitly typed as entities. They
  represent 247 strict normalized organization keys.
- The conservative resolver found 41 review candidates across 31 campaign entity
  keys—enough to continue L0 without weakening identity rules.
- Excluding `MIS...` values removes 229,610 eCheckbook rows spanning 73,709 raw
  names and 23 placeholder codes.
- One campaign election date is in 2104; 563 contract board-award dates use years
  between `0010` and `0023`.
- Campaign transaction IDs are unique. Campaign report IDs are not row keys.
