# Issue backlog

These are the issue-ready work items that could not be created during repository
bootstrap because the local GitHub CLI credential is not valid. Move them to
GitHub Issues once `gh auth status` succeeds.

## Configure repository governance

Create `major`, `minor`, and `patch` labels. Apply the `main` ruleset and merge
settings in `delivery.md`. Make all CI jobs and the PR release-label job required.
Verify a contributor PR requires Josh's code-owner approval, Josh can merge his
own PR, merge commits are the only enabled merge method, and an out-of-date but
otherwise passing branch is mergeable.

## Select the first application architecture

Choose between the static S3/CloudFront implementation and the
Lambda/S3-backed dynamic implementation from concrete product requirements.
Record the decision, artifact boundary, runtime, data refresh mechanism,
authentication boundary, and cost ceiling in an ADR before creating AWS
resources.

## Bootstrap Terraform and AWS identity

Complete the read-only discovery and reviewed account sequence in
`aws-bootstrap.md`. Create UAT and production accounts outside the Organizations
management account, Identity Center access, state bootstrap, and GitHub roles
whose trust requires immutable owner/repository IDs and environment context.
Then add the first real application module, exact module pins, provider locks,
TFLint configuration, tests, and parallel Terraform CI checks. Trivy is
explicitly out of scope; evaluate any future IaC scanner separately.

## Add PR previews and Terraform plan comments

Implement low-cost S3-prefix previews behind persistent UAT, cleanup on PR
close, a sanitized sticky production-plan summary for trusted PRs, and an opt-in
TTL-controlled `pr-<number>` Terraform workspace for infrastructure changes that
need full isolation.

## Implement intentional releases and production deployment

Add the manual semantic release workflow after a deployable artifact exists.
Calculate impact from all merged PR labels since the prior tag, build once,
generate and submit SBOMs, attest artifacts and SBOMs, create the GitHub release,
and honor a default-off `deploy_production` checkbox. Add a separate workflow to
deploy an existing release when the checkbox was left clear.

## Automate dependency updates

Enable a dependency bot for uv, GitHub Actions, Nix inputs, Terraform providers,
and exact Terraform module pins. Group low-risk patch updates, keep major module
updates isolated, and require the normal CI/data checks.

## Revisit vulnerability threshold policy

Keep the strict `uv audit` gate until it produces non-actionable noise. If that
happens, implement and test a documented policy that fails fixable HIGH and
CRITICAL findings while still reporting everything else; do not silently ignore
advisories by identifier without an expiry and rationale.
