# Questions for City of Austin data owners

Record the contact, date, and answer under each question. A verbal answer should
be followed by a written confirmation or linked public documentation.

## Campaign finance

1. Is `g4yx-aw9r` the canonical transaction-level source for all filings from
   2022 onward, and what records (amendments, in-kind contributions, loans,
   refunds, or schedules) require different treatment?
2. Is `3kfv-biw6` generated entirely from the canonical report/transaction
   datasets? What transformation and refresh lag produce it?
3. Which transaction/report identifier combination is stable across corrections
   and amended filings?
4. Which filer and donor type values definitively mean a legal entity rather
   than a person, household, committee, or uncategorized record?
5. Are street address, email, telephone, employer, and occupation fields intended
   to be returned by any API endpoint? The product will not publish direct
   contact/address fields even if an endpoint exposes them.
6. Are PDF links durable? Is there a supported way to link to a filing and row
   after a correction?

## Purchasing and payments

7. What is the stable identity behind `vendor_code`/`vendor_number`, and can
   codes be reassigned, merged, or split?
8. What exactly does the `MIS` prefix mean? Can City staff confirm that it is a
   placeholder/miscellaneous value unsuitable for vendor identity?
9. Does eCheckbook include reversals, voids, credits, interdepartmental entries,
   reimbursements, and pass-through payments? Which fields identify them?
10. Is there a durable payment-line identifier suitable for source-row links and
    duplicate detection?
11. Is the contracts dataset current-state only? Where are expired, superseded,
    amended, and historical contracts available?
    - L0 observation: 563 of 625 `brd_awd_dt` values use four-digit years from
      `0010` through `0023`. Are these intended to mean 2010–2023, and can the
      publisher correct them at the source?
12. How do contract numbers, purchase-order numbers, and payment records join,
    and which joins are expected to be one-to-many?
13. Are contract ceilings and purchase-order values commitments rather than paid
    amounts? Which values should never be summed together?

## Operations

14. What are the normal refresh cadence, correction policy, retention period,
    and known coverage gaps for each of the six datasets?
    - L0 observation: one report currently gives `election_date = 11/06/2104`.
      Is that a correctable source error?
15. Is there a supported notification channel for schema changes or dataset
    replacement?
16. Are bulk exports the recommended way to make periodic complete snapshots,
    and are there published rate or concurrency limits?
