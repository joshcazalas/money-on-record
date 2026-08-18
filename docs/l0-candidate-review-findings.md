# L0 candidate review findings — AI-assisted first pass

## Status

The candidate worksheet has a complete AI-assisted first-pass adjudication. It
is sufficient to support implementation of a beta whose cross-domain identities
remain visibly `unverified`; it is not a human verification result. Before any
identity displayed in the beta is labeled verified, audit all displayed Tier B
rows and the suggested strict-tier sample in the ignored local file
`data/derived/l0-ai-review-audit.md`.

## Method

- Grouped 41 candidate relationships by their underlying campaign identity so
  evidence could be reused across source-specific rows without merging the rows.
- Inspected each campaign-to-City relationship separately.
- Required durable HTTPS evidence from organization, regulatory, government, or
  comparable business-identity sources.
- Cross-checked restricted organization-address fields locally when available;
  those fields were not copied into version control.
- Attributed every worksheet row to an AI-assisted reviewer and preserved the
  candidate-level URLs and notes only in ignored local storage.
- Validated review completeness, controlled decisions and reasons, evidence URL
  shape, immutable evidence fingerprints, and candidate-set drift.

## Aggregate result

| Dimension | Candidates | `YES` | `NO` | `UNCERTAIN` |
| --- | ---: | ---: | ---: | ---: |
| Total | 41 | 41 | 0 | 0 |
| Tier A — strict normalized name | 28 | 28 | 0 | 0 |
| Tier B — narrow abbreviation/legal suffix | 13 | 13 | 0 | 0 |
| eCheckbook | 33 | 33 | 0 | 0 |
| Contracts | 2 | 2 | 0 | 0 |
| Purchase orders | 6 | 6 | 0 | 0 |

The versioned aggregate is
[`reports/reviews/l0-organization-candidate-review-summary.json`](../reports/reviews/l0-organization-candidate-review-summary.json).
It declares `AI_ASSISTED` provenance and excludes organization names, public
codes, candidate IDs, evidence URLs, notes, and reviewer names.

## Interpretation and limits

No false positive was found in this deliberately conservative candidate set.
That is evidence that the strict and narrow legal-suffix rules have high
precision for this sample; it is not proof of perfect precision and says nothing
about recall. The generator was designed to avoid difficult fuzzy matches, so a
perfect first-pass acceptance rate is plausible rather than representative of a
general entity resolver.

The concentrated audit risk is Tier B, especially legal-form differences,
association abbreviations, and identities repeated across City sources. Human
audit remains required before the result can support a product-level
verified-match claim. It does not block building or deploying a beta that
preserves the unverified status and explanation.
