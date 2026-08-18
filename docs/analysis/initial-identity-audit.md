# Initial organization identity audit

Snapshot audit created `2026-08-18T18:02:59.261437+00:00`. All counts are from the frozen artifact hashes in `data/derived/l0-identity-audit.json`.

## Campaign entity population

The official contributions projection contains **709 rows explicitly typed as entities**, representing 262 raw names and 247 strict normalized keys. These are the only campaign rows admitted to cross-domain matching.

## Purchasing/payment identity audit

| Source | Eligible rows | Strict keys | Invalid-code rows | Invalid-code names | Strict overlaps | Suffix overlaps |
|---|---:|---:|---:|---:|---:|---:|
| echeckbook | 1,886,956 | 20,690 | 229,610 | 73,709 | 22 | 28 |
| contracts | 625 | 365 | 0 | 0 | 2 | 2 |
| purchase-orders | 319,210 | 6,145 | 72 | 3 | 4 | 5 |

## Candidate set

The deterministic resolver produced **41 review candidates** across 31 campaign entity keys: 28 strict and 13 legal-suffix-only. Every row remains `UNREVIEWED`; no candidate is a verified identity link.

## Source-quality flags

- Campaign `transaction_id` values are unique in both transaction datasets.
- Campaign report `report_id` is not a row key; 300 duplicate non-null values were observed.
- Suspicious dates are retained as source values and must be resolved or labeled, not silently corrected.

  - `campaign-reports.election_date`: 1 suspicious rows; examples `11/06/2104`.
  - `contracts.brd_awd_dt`: 563 suspicious rows; examples `06/12/0021, 08/24/0019, 09/23/0023, 11/17/0022, 12/05/0020`.

## Current decision

The density gate is promising enough to continue L0: there are more than 25 conservative candidates without matching people. The identity gate has not passed until the review CSV is manually adjudicated and ambiguous cases are retained as negative regression examples.
