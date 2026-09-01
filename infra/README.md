# Infrastructure

The first application stack is a private S3 artifact bucket behind CloudFront.
S3 website hosting and public bucket access are intentionally disabled;
CloudFront reads objects through Origin Access Control. No Lambda resources are
created. A project-owned response-header policy supplies the site CSP, browser
capability restrictions, anti-indexing, and other security headers. Private
origin 403/404 responses render the reviewed `/404.html` page as HTTP 404.

```text
infra/
  components/static-site/  # one stateful root selected by named workspace
  modules/static_site/      # reusable private S3 and CloudFront stack
```

## Accounts and workspaces

Only the `uat` and `production` Terraform workspaces are deployable. The root
rejects `default` and every unknown workspace before it can plan resources. Its
workspace map fixes the environment, workload account, site bucket, and future
domain inputs together:

| Workspace | Workload account | Site bucket |
| --- | --- | --- |
| `uat` | `732006412638` | `money-on-record-uat-732006412638-site` |
| `production` | `134604497564` | `money-on-record-production-134604497564-site` |

The provider retains `allowed_account_ids` and assumes the matching
`MoneyOnRecordTerraformPlan` or `MoneyOnRecordTerraformDeploy` workload role.
Backend access remains on the deployment-account hub identity; no static AWS
credentials are inputs.

## Centralized state

The component uses the single deployment-account bucket
`joshcazalas-deployment-tfstate-245459924498`, native S3 locking, and these
exact non-default workspace objects:

```text
money-on-record/static-site/uat/terraform.tfstate
money-on-record/static-site/production/terraform.tfstate
```

There are no environment-specific backend files or application-owned state
buckets. Offline development and unprivileged CI use
`terraform init -backend=false`.

Automation selects a named workspace and supplies its matching execution role:

```bash
cd infra/components/static-site
export TF_VAR_aws_workload_role_arn=arn:aws:iam::732006412638:role/MoneyOnRecordTerraformPlan
export TF_WORKSPACE=uat
terraform init
terraform plan -lock=false
```

Do not commit local variables, plans, state, credentials, or account-discovery
output. Custom domain aliases remain empty until Cloudflare and ACM are ready;
the first deployment uses the generated `cloudfront.net` hostname.

## Reusable workflows

The permanent plan and deploy entry points are reserved at:

```text
.github/workflows/reusable-terraform-plan.yml
.github/workflows/reusable-terraform-deploy.yml
```

AWS trust is restricted to each reusable workflow's exact default-branch
`job_workflow_ref`. Privileged callers must use the reviewed default-branch
copies explicitly:

```yaml
uses: joshcazalas/money-on-record/.github/workflows/reusable-terraform-plan.yml@main
```

```yaml
uses: joshcazalas/money-on-record/.github/workflows/reusable-terraform-deploy.yml@main
```

The plan entry point accepts only `uat` or `production` from a same-repository
pull request. It assumes the environment-specific plan role and runs a read-only
plan with state locking disabled. The raw saved plan remains runner-local; only
sanitized text and resource counts are uploaded for the PR comment.

The deploy entry point accepts only `uat` or `production` from a trusted
default-branch caller. `terraform-deploy-uat.yml` deploys every exact revision
that lands on `main` to UAT and retains a default-off manual recovery dispatch.
Production has no merge trigger: `terraform-deploy-production.yml` accepts only
a published immutable semantic-version release whose tag resolves to the exact
commit. Each job prepares the site artifact, runs inside the matching GitHub
Environment, creates a locked saved plan covering infrastructure and site
objects, and applies that runner-local plan. A no-change plan is applied as a
normal successful no-op. Saved plans are never uploaded or retained.

`terraform-plan.yml` calls the trusted `@main` plan entry point for every
same-repository pull request. UAT and production plans run independently. Fork
pull requests skip both AWS plans because they cannot receive repository AWS
identities.

The manual release workflow calculates the next semantic version from every
merged PR label since the previous stable release. It builds versioned Python
and source assets, generates CycloneDX and SPDX SBOMs, submits the supported
dependency snapshot, creates GitHub artifact attestations, and publishes the
checksums and attestation bundles with the immutable release. Its default-off
checkbox can invoke the production deploy workflow for that exact release; the
same production workflow can deploy an existing immutable release manually.
GitHub OIDC supplies all AWS and attestation identities; no GitHub App, PAT, or
static AWS key is used.

Before a workspace's first deployment, its remote state object does not exist
and the read-only plan role cannot create it. For that initial plan only, the
workflow uses ephemeral local state with refresh disabled. Once remote state
exists, plans use the normal S3 backend. Access errors still fail the workflow.

## Complete environment deployment

Terraform owns the rendered browser files as `aws_s3_object` resources in the
same state as the bucket and CloudFront distribution. The trusted deploy job
prepares and verifies the artifact before AWS authentication, creates one fresh
saved plan, and applies that exact plan. The apply therefore creates or updates
infrastructure, publishes changed files, and deletes stale state-owned files as
one environment deployment.

UAT builds the deterministic artifact from the exact current `main` revision.
Production downloads and verifies the site ZIP and checksum from the selected
immutable release. HTML and manifests use revalidation cache controls while
content-hashed assets use immutable caching, so no mutable invalidation side
effect or separate publishing identity is required.
