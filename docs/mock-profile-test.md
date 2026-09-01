# Static explorer usability test

The beta contains source-specific candidate and committee pages plus a separate
unverified organization-to-City-vendor example. Source-specific campaign pages
do not claim a cross-domain person identity.

## Deployed-beta participant gate

Status: **DEFERRED UNTIL A NAVIGABLE BETA IS DEPLOYED**

This test does not block implementation or the first AWS deployment. A relevant
participant should receive a stable browser URL with representative data—not a
GitHub repository, local HTML file, setup instructions, or hypothetical product
description. Until then, preserve the script and do not claim external
validation.

- [ ] One reporter, campaign-finance researcher, or civic-data user has completed the test.
- [ ] Participant role and test date are recorded without unnecessary personal details.
- [ ] Any screen recording or notes have explicit participant consent.

## Five-task script

Ask the participant to think aloud and avoid explaining the interface first.

1. Find a candidate or committee by name, office, or district.
2. Identify its largest reported contributors and explain what the displayed
   total includes.
3. Filter the displayed contribution rows by year or donor type, then open one
   official filing.
4. Explain how correction-marked rows affect what can and cannot be concluded
   from the reported-row total.
5. Open the linked organization example and explain why its campaign-to-City
   vendor identity remains unverified.

## Pass signals

- A candidate, committee, or district can be found without assistance.
- Full-snapshot summaries and sampled source rows are not confused with one
  another.
- The participant notices the unverified status before treating the separate
  cross-domain organization link as fact.
- Totals and individual source filings can be found without assistance.
- The participant understands that juxtaposition is not evidence of influence or wrongdoing.
- At least one concrete use case remains valuable without person matching.

## Results

Status: **NOT YET TESTED — TRACKED IN ISSUE #14**

Source-link verification on September 1, 2026: the checked-in campaign
publication was derived from 121,808 City contribution rows, excludes 179 rows
without a recipient, and groups the remaining 121,629 rows into 87 recipient
profiles. It retains only reviewed fields and at most the one hundred most recent
rows per profile. The existing linked-organization projection still contains 53
campaign rows and 208 eCheckbook rows.

Record observations, confusion, requested context, and resulting changes here.
Do not describe the beta as externally validated until an eligible participant
has actually performed the tasks.
