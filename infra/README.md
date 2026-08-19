# Infrastructure

The first application stack is a private S3 artifact bucket behind CloudFront.
S3 website hosting and public bucket access are intentionally disabled;
CloudFront reads objects through Origin Access Control. No Lambda resources are
created.

```text
infra/
  modules/static_site/  # reusable private S3 and CloudFront stack
  environments/uat/     # UAT state and account boundary
  environments/prod/    # production state and account boundary
```

Each environment root requires its exact 12-digit AWS account ID. The AWS
provider's `allowed_account_ids` guard stops an apply against the wrong account.
The roots use separate S3 backends with native lockfiles; create those state
buckets through the account bootstrap before running an application plan.

Copy the example inputs locally, replace the account ID, and initialize with the
environment's backend file:

```bash
cd infra/environments/uat
cp terraform.tfvars.example terraform.tfvars
cp backend.hcl.example backend.hcl
terraform init -backend-config=backend.hcl
terraform plan
```

Do not commit `terraform.tfvars`, `backend.hcl`, plans, state, credentials, or
account-discovery output. Custom domain aliases remain empty until the
Cloudflare and ACM work is ready; the first deployment uses the generated
`cloudfront.net` hostname.
