# Infrastructure

The first application stack is a private S3 artifact bucket behind CloudFront.
S3 website hosting and public bucket access are intentionally disabled;
CloudFront reads objects through Origin Access Control. No Lambda resources are
created.

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

Once access is enabled, automation selects a named workspace and supplies only
the matching execution-role ARN:

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

The plan entry point accepts only `uat` or `production`, only from a
same-repository pull request. It assumes the environment-specific plan hub,
initializes the committed S3 backend, and runs a read-only plan with state
locking disabled. It does not save or upload a plan. The deploy entry point
remains a fail-closed bootstrap; no Terraform apply path exists.

`terraform-plan.yml` calls the trusted `@main` plan entry point for every
same-repository pull request. UAT runs first; the production plan starts only
after UAT succeeds. Fork pull requests skip both AWS jobs because their code
cannot be given the repository's plan identities.

Before the first deployment, a named workspace has no remote state object and
the read-only plan identity cannot create one. In that case only, the workflow
plans against ephemeral empty local state with refresh disabled. The first
authorized deployment creates the remote workspace state; subsequent pull
requests automatically plan against that state. An access error is never
treated as an absent workspace.

The legacy `aws-oidc-identity-test.yml` path is deliberately untrusted. It only
verifies that all plan and deploy hub roles deny its OIDC token.
