# Initial full-snapshot source profile

All six August 18, 2026 bulk exports met their expected minimum row counts, and
every configured contract field resolved through the frozen Socrata metadata.
The JSON reports contain exact null counts for every observed field; this page
summarizes the fields most relevant to L0 decisions.

| Source | Rows | Primary date coverage | Identity/key result |
|---|---:|---|---|
| Campaign reports | 1,086 | Filed 2023-01-03–2026-08-05 | `report_id` has 786 distinct values and 300 duplicate non-null occurrences; 174 rows have no `filer_name` |
| Campaign transactions | 131,122 | Transaction 2022-01-16–2026-07-25 | All 131,122 `transaction_id` values are present and unique; 20,144 distinct transactor names |
| Campaign contributions | 120,849 | Contribution 2022-01-16–2026-07-24 | All 120,849 `transaction_id` values are present and unique; 180 rows have no recipient |
| eCheckbook | 2,116,566 | Payment 2008-10-01–2026-08-14 | No null vendor names or codes; 94,475 raw names and 19,178 codes before placeholder exclusion |
| Contracts | 625 | Effective start 2008-11-24–2024-01-01 | All 625 `row_key` values are present and unique; 102 rows have no end date |
| Purchase orders | 319,282 | Award 2009-10-01–2026-07-31 | No null legal names or vendor codes; 6,222 raw names and 5,745 codes before placeholder exclusion |

Exact reports:

- [`campaign-reports.json`](../../reports/profiles/20260818T180135Z-campaign-reports.json)
- [`campaign-transactions.json`](../../reports/profiles/20260818T180139Z-campaign-transactions.json)
- [`campaign-contributions.json`](../../reports/profiles/20260818T180140Z-campaign-contributions.json)
- [`echeckbook.json`](../../reports/profiles/20260818T180214Z-echeckbook.json)
- [`contracts.json`](../../reports/profiles/20260818T180214Z-contracts.json)
- [`purchase-orders.json`](../../reports/profiles/20260818T180219Z-purchase-orders.json)

## Data-quality holds

- One campaign report gives `election_date = 11/06/2104`.
- Contract `brd_awd_dt` is not usable as a date without publisher guidance: 563
  rows use years from `0010` through `0023`, and another 62 are null.
- `report_id` identifies a filing but is not a unique report-detail row key.
- eCheckbook and purchase orders do not declare a unique row identifier in the
  current contract; source-row lineage must use the frozen artifact plus an exact
  compound filter or a generated internal row hash.

These values remain exactly as published. L0 will label or exclude them until the
City confirms semantics; it will not silently repair the years or invent keys.
