# Manual organization-candidate review

`mor-l0 candidates --limit 50` creates a deterministic, stratified review CSV.
Tier A differs only by typography; Tier B additionally removes a trailing legal
suffix. Both are candidates, never verified links.

For every row:

1. Open the official campaign filing and purchasing/payment record.
2. Confirm the records refer to the same legal organization using independent
   evidence such as official websites, Texas entity records, contract documents,
   or clearly shared business identifiers.
3. Use the two `*_source_rows_url` columns to inspect the exact official rows
   behind the frozen aggregate; the artifact SHA columns pin the local snapshot.
4. Set `same_organization` to `YES`, `NO`, or `UNCERTAIN`.
5. Add at least one durable `external_evidence_url` and a short reason. Name similarity by
   itself is not enough evidence.
6. Leave `review_status` as `UNREVIEWED` until a human completes the row.

Reject ambiguous abbreviations, franchises/chapters, parent/subsidiary pairs,
distinct professional entities, individual/organization collisions, and records
whose only shared identifier is an `MIS...` code. Preserve rejected candidates;
they are regression cases for future resolver changes.
