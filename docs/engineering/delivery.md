# Delivery and infrastructure design

This is the target lifecycle, staged so the repository gets useful controls
early without pretending that an application artifact or AWS topology already
exists.

Deferred implementation is captured as issue-ready work in
[`issue-backlog.md`](issue-backlog.md).
The account and CI identity bootstrap is specified separately in
[`aws-bootstrap.md`](aws-bootstrap.md).

## Pull requests and repository rules

The repository contains a `CODEOWNERS` default assigning all paths to
`@joshcazalas`. Configure the `main` ruleset as follows:

1. Require pull requests and one code-owner approval.
2. Allow repository administrators to bypass the pull-request approval rule so
   Josh can merge his own PRs. Do not grant that bypass to contributors.
3. Require the CI job checks and the `Exactly one major, minor, or patch label`
   check.
4. Use loose required status checks: do not require branches to be up to date
   before merging.
5. Allow merge commits only; disable squash and rebase merges.
6. Block force pushes and branch deletion.

Create the `major`, `minor`, and `patch` labels. Every PR must carry exactly one;
the label expresses release impact, not whether a release happens immediately.

Forked PRs must never receive AWS credentials. They can run all current offline
checks. Infrastructure plans for untrusted forks require maintainer approval or
must run from a maintainer-owned branch.

## Terraform layout and checks

The static-site infrastructure uses one component root and one reusable module:

```text
infra/
  components/static-site/  # centralized backend and workspace configuration
  modules/static_site/      # private S3 and CloudFront composition
```

Only the named `uat` and `production` workspaces are valid. They select fixed
configuration for workload accounts `732006412638` and `134604497564`
respectively; `default` and unknown workspaces fail closed. Workspaces are not
the security boundary: the provider's `allowed_account_ids`, exact workload
role assumption, and separate workload accounts enforce that boundary.

Both workspaces use the centralized deployment-account state bucket. The S3
backend's `workspace_key_prefix = "money-on-record/static-site"` and
`key = "terraform.tfstate"` produce these independent objects:

```text
money-on-record/static-site/uat/terraform.tfstate
money-on-record/static-site/production/terraform.tfstate
```

Use the S3 backend's native `use_lockfile = true` locking. Enable encryption,
public-access blocking, and bucket versioning on the state bucket. DynamoDB
locking is deprecated and should not be introduced. Commit the component root's
multi-platform `.terraform.lock.hcl`.

The provider lockfile does not lock remote modules. Adopt a
`terraform-aws-modules` module only when its abstraction is useful, choose the
latest stable major at adoption time, and pin its exact version. Dependency-bot
PRs should propose subsequent upgrades. Small resources are often clearer as
direct Terraform than through a large general-purpose module.

Terraform PR checks should run independently where possible:

- `terraform fmt -check -recursive`
- `terraform init -backend=false`
- `terraform validate`
- `terraform test` for module behavior
- `tflint --init` and recursive TFLint with the AWS ruleset
- committed multi-platform provider-lock verification
- generated `terraform-docs` drift checks
- plan generation against the target environment for trusted PRs

Add policy-as-code for required tags, approved regions, encryption, public
access, and cost ceilings once the first resources exist. Infracost is useful
for change visibility but should begin as advisory. Do not publish or retain a
raw Terraform plan where unauthorized users can read it; plan files can contain
sensitive values. A sticky PR comment should show a sanitized resource/action
summary and link to the protected job log.

Trivy is excluded by policy. Do not add its binary, GitHub Action, container, or
an installer wrapper. Select any future IaC scanner through an explicit
supply-chain review; Terraform validation, TFLint, tests, and project-owned
policy-as-code remain the initial controls.

## Low-cost previews

Creating a CloudFront distribution per PR is slow and unnecessarily expensive.
For the static-site option, prefer one persistent UAT distribution with an S3
prefix per PR, such as `previews/pr-123/`, and post the preview URL to the PR.
Delete the prefix when the PR closes. If the application becomes dynamic, use
the same principle with isolated Lambda aliases or an explicitly provisioned
preview stack only when isolation is needed.

Infrastructure changes should produce a sticky production-plan summary on the
PR and deploy to UAT after merge to `main`. The current component intentionally
rejects preview workspaces; any future preview infrastructure requires a
separately reviewed state, naming, TTL, and cleanup contract. Ordinary static
previews remain application artifacts under the persistent UAT distribution.

## Intentional releases

Merging a PR does not create a release. The release workflow will be a manual
`workflow_dispatch` with a `deploy_production` boolean defaulting to false.

At release time it should:

1. Find merge commits on `main` since the latest semantic-version tag and map
   them to their merged PRs.
2. Reject any PR that lacks exactly one release label.
3. Choose the greatest impact (`major` > `minor` > `patch`) and calculate the
   next version.
4. Build immutable deployment artifacts and generate release notes from those
   PRs.
5. Generate SBOMs, attest the artifacts and SBOMs with GitHub OIDC, create the
   GitHub release, and submit the supported dependency snapshot.
6. If `deploy_production` was selected, invoke the reusable production deploy
   job for that exact release artifact—never rebuild from the branch.

If the checkbox is left clear, a separate manual deploy workflow should accept
an existing release version. Production can also use a protected GitHub
Environment if a second human confirmation becomes desirable.

## SBOM and provenance boundary

No single scanner can truthfully describe “every piece of software.” The release
bundle should include complementary evidence:

- uv CycloneDX output for the complete locked Python dependency graph;
- Syft SPDX JSON for the actual deployable artifact;
- the pinned GitHub Action inventory, `flake.lock`, and Terraform provider lock
  files as build/repository dependency evidence; and
- GitHub artifact attestations for each deployable artifact and attached SBOM.

Build tools belong in provenance; runtime and bundled packages belong in the
artifact SBOM. Submit the release SPDX snapshot through GitHub's dependency
submission API and attach both formats to the release.

GitHub's dependency graph also derives dependencies from manifests and lockfiles
on the default branch. Therefore it cannot be forced to represent *only* the
latest release while `main` moves ahead. We can submit a clearly correlated
snapshot for every release, but the graph will also reflect current default-
branch data. Release attestations and attached SBOMs are the authoritative
historical record.

The actual release, attestation, preview, and Terraform workflows should be
implemented as soon as the first deployable application and AWS root module
exist; before that, they would be untestable ceremony with no valid artifact or
plan target.
