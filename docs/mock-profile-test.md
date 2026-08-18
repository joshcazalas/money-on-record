# Static profile usability test

Prototype: [`../prototypes/organization-profile.html`](../prototypes/organization-profile.html)

The page intentionally uses an unverified strict-name candidate and labels that status at the
top, beside the identity explanation, and in the footer. It is a local research artifact, not a
publication decision.

## Participant gate

- [ ] One reporter, campaign-finance researcher, or civic-data user has completed the test.
- [ ] Participant role and test date are recorded without unnecessary personal details.
- [ ] Any screen recording or notes have explicit participant consent.

## Five-task script

Ask the participant to think aloud and avoid explaining the interface first.

1. What claim do you think this page is making about the organization?
2. Find the campaign total and explain what records it includes.
3. Find the City-payment total and open the official rows behind it.
4. How confident are you that the two names refer to the same organization? What evidence would
   you need before publication?
5. What important question can this page answer, and what question can it not answer?

## Pass signals

- The participant notices the unverified status before treating the cross-domain link as fact.
- Both totals and source rows can be found without assistance.
- The participant understands that juxtaposition is not evidence of influence or wrongdoing.
- At least one concrete use case remains valuable without person matching.

## Results

Status: **NOT YET TESTED**

Source-link verification on August 18, 2026: the official APIs returned 53 rows
and `$240,133.82` for the campaign filter, and 208 rows and `$106,072.10` for the
eCheckbook filter. These match the frozen-snapshot calculations displayed in the
prototype. The links now request only allowlisted fields, and a local scan of
both exact frozen projections produced zero PII-pattern findings.

Record observations, confusion, requested context, and resulting changes here. Do not mark the L0
usability gate complete until an eligible external participant has actually performed the tasks.
