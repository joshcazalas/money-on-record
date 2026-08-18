# L0 acceptance gates

L0 answers one question: **can Money on Record publish useful organization
profiles from official Austin records without weakening source integrity or
privacy standards?** Hosting and application architecture are intentionally out
of scope until these gates pass.

## Required evidence

- [x] Versioned contracts name all six v1 sources and distinguish canonical,
  official-projection, and current-only roles.
- [x] Acquisition is content-addressed and emits URL, timestamp, response
  headers, byte length, and SHA-256 manifests.
- [x] Public schemas use explicit allowlists; unknown columns fail closed.
- [x] A second scanner rejects common direct-contact PII patterns in allowed
  text fields.
- [x] Name normalization is deterministic, tested, and organization-only.
- [x] `MIS...` vendor codes are excluded from cross-domain identity evidence.
- [x] Freeze current metadata and reconcile every configured field to it.
- [x] Acquire and exactly profile every complete v1 source snapshot.
- [x] Generate value-free fixtures from every source and commit only fixtures
  that pass the privacy check.
- [ ] Human-audit the completed AI-assisted review of 41 cross-domain
  organization candidates, focusing on all Tier B rows and a strict-tier sample;
  preserve evidence and reasons locally and commit only the aggregate summary.
- [ ] Test one static organization profile with at least one reporter or
  civic-data user; write down what was and was not useful.
- [x] Every displayed aggregate in the mock profile links to the exact source
  rows used to calculate it.
- [ ] Resolve or document every City data-owner question in
  [`city-questions.md`](city-questions.md).

## Pass decision

Proceed to product code only if all six datasets can be replayed, the public
projection passes a hostile PII review, and enough non-placeholder organizations
survive manual review to make a profile useful without matching people.

## Kill or pivot decision

If profiles remain sparse after conservative matching, narrow the product to
source-specific exploration or stop. Do not compensate by fuzzy-matching people,
trusting placeholder vendor IDs, exposing raw address/contact columns, or
presenting ambiguous organizations as verified matches.
