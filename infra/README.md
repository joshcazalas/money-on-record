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
buckets. Do not initialize the backend until the foundation enables its scoped
state policy. Offline development and CI use `terraform init -backend=false`.

Once access is enabled, automation selects a named workspace and supplies only
the matching execution-role ARN:

```bash
cd infra/components/static-site
export TF_VAR_aws_workload_role_arn=arn:aws:iam::732006412638:role/MoneyOnRecordTerraformPlan
terraform init
terraform workspace select -or-create uat
export TF_WORKSPACE=uat
terraform plan
```

Do not commit local variables, plans, state, credentials, or account-discovery
output. Custom domain aliases remain empty until Cloudflare and ACM are ready;
the first deployment uses the generated `cloudfront.net` hostname.

## Reusable workflow bootstrap

The permanent plan and deploy entry points are reserved at:

```text
.github/workflows/reusable-terraform-plan.yml
.github/workflows/reusable-terraform-deploy.yml
```

They intentionally fail closed until AWS trust is restricted to their exact
`job_workflow_ref` claims and scoped state access is enabled. Future privileged
caller jobs must use the reviewed default-branch copies explicitly:

```yaml
uses: joshcazalas/money-on-record/.github/workflows/reusable-terraform-plan.yml@main
```

```yaml
uses: joshcazalas/money-on-record/.github/workflows/reusable-terraform-deploy.yml@main
```
