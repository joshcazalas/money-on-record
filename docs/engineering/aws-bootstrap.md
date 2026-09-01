# AWS organization and GitHub OIDC bootstrap

This is the bootstrap plan for Money on Record. It intentionally separates
human administration, CI identity, Terraform state, UAT, and production before
the first workload resource is created.

Do not paste AWS access keys, root credentials, MFA codes, or GitHub tokens into
an issue, chat, Terraform variable, repository secret, or workflow. Human
bootstrap uses AWS IAM Identity Center; GitHub uses short-lived OIDC credentials.

## Target account structure

Use one management account and three member accounts:

```text
AWS Organization
├── management account       billing, Organizations, Identity Center only
├── Deployments OU
│   └── deployment            OIDC hub and centralized application state
└── Workloads OU
    ├── NonProduction OU
    │   └── workloads-uat     UAT and shared low-cost PR previews
    └── Production OU
        └── workloads-prod    production only
```

The existing account may already be the Organizations management account. Do
not assume that until the read-only discovery commands below confirm it. AWS
workloads and GitHub deployment roles do not belong in the management account;
service control policies also do not constrain principals there.

A dedicated security/log-archive account can be introduced when centralized
security services are selected. It is not required merely to begin one
cost-conscious workload, and this plan does not silently enable recurring-cost
services.

## Phase 1: read-only discovery

After configuring the AWS CLI with the existing account, collect this output
locally. Account IDs are identifiers rather than secrets, but review the output
before sharing it:

```bash
aws sts get-caller-identity
aws organizations describe-organization
aws organizations list-accounts
aws organizations list-roots
aws organizations list-organizational-units-for-parent --parent-id <ROOT_ID>
```

Also confirm:

- root access uses a passkey or hardware MFA and has no access keys;
- the root email and recovery phone are current;
- billing and security alternate contacts are configured;
- IAM Identity Center exists and its home region is known; and
- there are no unexpected IAM users, access keys, roles, organization accounts,
  delegated administrators, or paid services.

Discovery is read-only. Account creation, Organizations changes, and identity
changes require an explicit reviewed bootstrap step.

## Phase 2: human access and accounts

1. Enable IAM Identity Center in the Organizations management account if it is
   not already enabled.
2. Create Josh's Identity Center user with phishing-resistant MFA where
   available. Do not create a normal IAM user for daily administration.
3. Create a bootstrap administrator permission set. Use it only for setup and
   keep routine workload access narrower afterward.
4. Create the `Workloads` OU and the UAT and production member accounts. Each
   AWS account requires a unique controlled email address; aliases are fine when
   the mail provider supports them.
5. Assign the bootstrap permission set to Josh in both workload accounts.
6. Add account-level budgets and notifications before deploying resources.
7. Attach a reviewed guardrail preventing member accounts from leaving the
   organization or closing themselves. Do not introduce broad region or service
   denies until their effects are tested.

The management account remains for billing, Organizations, Identity Center, and
the few operations that require it. It does not host Lambda, S3 application
buckets, CloudFront, Terraform state, or GitHub Actions roles.

## Phase 3: immutable GitHub identity

Money on Record was created after GitHub's July 15, 2026 immutable-subject
cutoff. Its default OIDC subject should therefore contain the numeric personal
account owner ID and repository ID:

```text
repo:joshcazalas@<OWNER_ID>/money-on-record@<REPOSITORY_ID>:environment:<ENVIRONMENT>
```

This prevents an account or repository that later reuses the same names from
receiving the same subject. Verify the repository setting explicitly instead of
relying only on its creation date:

```bash
gh api repos/joshcazalas/money-on-record/actions/oidc/customization/sub
gh api user --jq .id
gh api repos/joshcazalas/money-on-record --jq .id
```

If immutable subjects are not enabled, opt in through the repository Actions
OIDC setting or its REST endpoint before creating trust policies. Record these
non-secret values in the reviewed Terraform configuration:

- GitHub owner ID (Josh's immutable personal-account ID)
- repository ID
- Josh's actor ID
- UAT AWS account ID
- production AWS account ID

GitHub emits `actor_id`, `repository_id`, and `repository_owner_id` as distinct
claims. Current AWS IAM can evaluate those claims directly, so no custom subject
template is required solely to use them.

## Phase 4: deployment-account OIDC hub

Create one GitHub Actions OIDC provider in the deployment account:

```text
issuer:   https://token.actions.githubusercontent.com
audience: sts.amazonaws.com
```

Create separate least-privilege hub roles for each environment:

- `MoneyOnRecordPlanUat` and `MoneyOnRecordPlanProd` for pull-request plans;
- `MoneyOnRecordDeployUat` and `MoneyOnRecordDeployProd` for protected
  environment deployments.

Each hub may access only its centralized state object and assume only its exact
workload-account execution role. The workload accounts contain no GitHub OIDC
provider. Their `MoneyOnRecordTerraformPlan` and
`MoneyOnRecordTerraformDeploy` roles trust only the matching deployment-account
hub role.

The plan role is not available to forked PRs. Deployment roles are available
only to jobs using their corresponding protected GitHub Environment.

Every hub trust policy must use `StringEquals` for the audience, immutable
subject, repository ID, owner ID, and exact reusable `job_workflow_ref`.
Deployment trust also requires the environment and `main` ref; production
requires Josh's immutable actor ID. The production deployment hub trust has
this shape:

```json
{
  "StringEquals": {
    "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
    "token.actions.githubusercontent.com:sub": "repo:joshcazalas@<OWNER_ID>/money-on-record@<REPOSITORY_ID>:environment:production",
    "token.actions.githubusercontent.com:repository_id": "<REPOSITORY_ID>",
    "token.actions.githubusercontent.com:repository_owner_id": "<OWNER_ID>",
    "token.actions.githubusercontent.com:actor_id": "<JOSH_ACTOR_ID>",
    "token.actions.githubusercontent.com:environment": "production",
    "token.actions.githubusercontent.com:ref": "refs/heads/main",
    "token.actions.githubusercontent.com:job_workflow_ref": "joshcazalas/money-on-record/.github/workflows/reusable-terraform-deploy.yml@refs/heads/main"
  }
}
```

The `job_workflow_ref` must be
`joshcazalas/money-on-record/.github/workflows/reusable-terraform-deploy.yml@refs/heads/main`.
The plan roles similarly require the main-branch
`reusable-terraform-plan.yml` ref and the immutable pull-request subject. Do not
use a wildcard `sub` for this repository or owner. The federated principal is
the deployment account's exact `token.actions.githubusercontent.com` provider
ARN, and the only web-identity trust action is
`sts:AssumeRoleWithWebIdentity`.

UAT uses the same owner/repository constraints with `environment:uat` and its
own account and role. Decide whether UAT should require Josh's actor ID when its
automatic deployment trigger is finalized. Production always does.

## Phase 5: GitHub deployment boundary

Create `uat` and `production` GitHub Environments. Restrict deployment branches
to `main` and release tags as appropriate. Production deployment originates
only from the intentional release/deploy workflow.

Only the AWS-assuming job receives:

```yaml
permissions:
  contents: read
  id-token: write
```

All lint, test, build, and untrusted PR jobs retain `contents: read` and cannot
mint an AWS credential. Pin the AWS credential action to a full commit SHA,
specify `allowed-account-ids`, use a run-specific role session name, and request
the exact role for the target environment. No AWS access key is stored in
GitHub.

The first OIDC test chains through each hub to its matching workload role and
performs only `aws sts get-caller-identity`. Confirm the returned account and
role before granting state or workload permissions. Also test the opposite
workload role, wrong environment/ref, and pull-request access to deployment
roles as expected denials.

## Phase 6: centralized application state

The AWS foundation creates one application-state bucket in the deployment
account. Application repositories must not create or manually bootstrap another
state bucket. The centralized bucket has:

- public access blocked;
- versioning enabled;
- server-side encryption enabled;
- TLS-only bucket policy;
- least-privilege object access for the matching plan/deploy hub roles;
- lifecycle protection against accidental destroy; and
- native Terraform locking through `use_lockfile = true`.

Money on Record uses one `infra/components/static-site` root with explicit
`uat` and `production` workspaces. The backend's workspace prefix resolves them
to these independently permissioned state objects:

```text
money-on-record/static-site/uat/terraform.tfstate
money-on-record/static-site/production/terraform.tfstate
```

The deployment-account hub identity accesses the backend; the AWS provider then
assumes the matching workload execution role. Cross-environment state and role
access is forbidden. Because no application state predates this design, there
is no migration or temporary local state.

Commit the component root's generated multi-platform `.terraform.lock.hcl`.
Exact-pin remote modules because provider lockfiles do not lock module versions.

## Inputs needed before implementation

No account or identity mutation should begin until these are known:

- whether the existing AWS account is the Organizations management account;
- existing Organization/OU/account inventory;
- Identity Center status and home region;
- controlled unique email aliases for UAT and production accounts;
- preferred primary AWS region;
- GitHub owner, repository, and actor numeric IDs; and
- whether the GitHub repository is public or private and which plan features are
  available for Environment protection rules.

These inputs contain no passwords or access keys. Once collected, the next
deliverable is a reviewed bootstrap runbook and the smallest Terraform roots for
state and OIDC—still without deploying the application itself.
