import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "infra" / "components" / "static-site"


def _quoted_assignment(source: str, name: str) -> str:
    match = re.search(rf"^\s*{re.escape(name)}\s*=\s*\"([^\"]+)\"\s*$", source, re.MULTILINE)
    assert match is not None, f"missing quoted backend assignment: {name}"
    return match.group(1)


def test_centralized_backend_derives_exact_workspace_keys() -> None:
    backend = (COMPONENT / "backend.tf").read_text(encoding="utf-8")

    assert _quoted_assignment(backend, "bucket") == ("joshcazalas-deployment-tfstate-245459924498")
    assert _quoted_assignment(backend, "key") == "terraform.tfstate"
    assert _quoted_assignment(backend, "workspace_key_prefix") == ("money-on-record/static-site")
    assert _quoted_assignment(backend, "region") == "us-east-1"
    assert re.search(r"^\s*encrypt\s*=\s*true\s*$", backend, re.MULTILINE)
    assert re.search(r"^\s*use_lockfile\s*=\s*true\s*$", backend, re.MULTILINE)
    assert re.search(
        r'^\s*allowed_account_ids\s*=\s*\["245459924498"\]\s*$',
        backend,
        re.MULTILINE,
    )

    prefix = _quoted_assignment(backend, "workspace_key_prefix")
    key = _quoted_assignment(backend, "key")
    derived_keys = {workspace: f"{prefix}/{workspace}/{key}" for workspace in ("uat", "production")}

    assert derived_keys == {
        "uat": "money-on-record/static-site/uat/terraform.tfstate",
        "production": "money-on-record/static-site/production/terraform.tfstate",
    }


def test_environment_roots_were_replaced_by_one_component() -> None:
    assert COMPONENT.is_dir()
    assert not (ROOT / "infra" / "environments").exists()


def test_reusable_terraform_plan_is_read_only_and_environment_bound() -> None:
    source = (ROOT / ".github" / "workflows" / "reusable-terraform-plan.yml").read_text(
        encoding="utf-8"
    )

    assert "workflow_call:" in source
    assert "contents: read" in source
    assert "id-token: write" in source
    assert "CALLER_REPOSITORY" in source
    assert "Fork pull requests cannot request AWS-backed Terraform plans" in source
    assert "TF_WORKSPACE: ${{ inputs.environment }}" in source
    assert "terraform init" in source
    assert "-backend-config=use_lockfile=false" in source
    assert (
        "STATE_KEY: money-on-record/static-site/${{ inputs.environment }}/terraform.tfstate"
        in source
    )
    assert "Detect selected workspace state" in source
    assert "if: steps.state.outputs.exists == 'true'" in source
    assert "if: steps.state.outputs.exists == 'false'" in source
    assert 'mv -- backend.tf "$BACKEND_STASH_PATH"' in source
    assert "-backend=false" in source
    assert "plan_args+=(-refresh=false)" in source
    assert "-input=false" in source
    assert "-lockfile=readonly" in source
    assert 'terraform plan "${plan_args[@]}"' in source
    assert "-lock=false" in source
    assert "-detailed-exitcode" in source
    assert "S3 therefore returns 404 while the opposite state is" in source
    assert 'if [[ "$state_status" -eq 0 ]]' in source
    assert "AccessDenied|\\(404\\)|Not Found|NoSuchKey" in source
    assert "terraform workspace new" not in source
    assert "terraform workspace select" not in source
    assert "terraform apply" not in source
    assert "upload-artifact" not in source


def test_reusable_terraform_deploy_is_uat_only_and_bootstrap_safe() -> None:
    source = (ROOT / ".github" / "workflows" / "reusable-terraform-deploy.yml").read_text(
        encoding="utf-8"
    )

    assert "workflow_call:" in source
    assert source.count("contents: read") == 2
    assert source.count("id-token: write") == 2
    assert "environment: ${{ inputs.environment }}" in source
    assert "Only the UAT bootstrap deployment is enabled" in source
    assert "workflow_dispatch" in source
    assert "refs/heads/main" in source
    assert "EXPECTED_REPOSITORY_ID: '1338755168'" in source
    assert "EXPECTED_OWNER_ID: '73436834'" in source
    assert "EXPECTED_WORKLOAD_ACCOUNT_ID: '732006412638'" in source
    assert "MoneyOnRecordDeployUat" in source
    assert "MoneyOnRecordTerraformDeploy" in source
    assert "money-on-record/static-site/uat/terraform.tfstate" in source
    assert "money-on-record/static-site/production/terraform.tfstate" in source
    assert "cancel-in-progress: false" in source
    assert "persist-credentials: false" in source
    assert "terraform init" in source
    assert "-lockfile=readonly" in source
    assert "-lock-timeout=5m" in source
    assert '-out="$plan_file"' in source
    assert "terraform show -json" in source
    assert "actual_changes" in source
    assert "expected_changes" in source
    assert "UAT bootstrap plan: 9 additions, 0 changes, 0 destroys" in source
    assert "terraform apply" in source
    assert '"$RUNNER_TEMP/money-on-record-uat.tfplan"' in source
    assert "Verify state and convergence" in source
    assert "Post-apply plan | No changes" in source
    assert "terraform destroy" not in source
    assert "upload-artifact" not in source
    assert "-lock=false" not in source
    assert "use_lockfile=false" not in source

    expected_resources = {
        "terraform_data.workspace_contract",
        "module.static_site[0].aws_s3_bucket_policy.site",
        "module.static_site[0].module.cdn.aws_cloudfront_distribution.this[0]",
        'module.static_site[0].module.cdn.aws_cloudfront_origin_access_control.this[\\"site\\"]',
        "module.static_site[0].module.site_bucket.aws_s3_bucket.this[0]",
        "module.static_site[0].module.site_bucket.aws_s3_bucket_ownership_controls.this[0]",
        "module.static_site[0].module.site_bucket.aws_s3_bucket_public_access_block.this[0]",
        "module.static_site[0].module.site_bucket.aws_s3_bucket_server_side_encryption_configuration.this[0]",
        "module.static_site[0].module.site_bucket.aws_s3_bucket_versioning.this[0]",
    }
    assert all(resource in source for resource in expected_resources)


def test_uat_deploy_requires_manual_confirmation_and_trusted_main_workflow() -> None:
    source = (ROOT / ".github" / "workflows" / "terraform-deploy-uat.yml").read_text(
        encoding="utf-8"
    )
    trusted_call = (
        "uses: joshcazalas/money-on-record/.github/workflows/reusable-terraform-deploy.yml@main"
    )

    assert "workflow_dispatch:" in source
    assert "confirm_uat_deployment:" in source
    assert "default: false" in source
    assert "if: inputs.confirm_uat_deployment" in source
    assert "permissions: {}" in source
    assert "contents: read" in source
    assert "id-token: write" in source
    assert source.count(trusted_call) == 1
    assert "environment: uat" in source
    assert "pull_request:" not in source
    assert "push:" not in source
    assert "schedule:" not in source
    assert "environment: production" not in source


def test_pull_request_plans_call_only_the_trusted_main_workflow() -> None:
    source = (ROOT / ".github" / "workflows" / "terraform-plan.yml").read_text(encoding="utf-8")
    trusted_call = (
        "uses: joshcazalas/money-on-record/.github/workflows/reusable-terraform-plan.yml@main"
    )

    assert "pull_request:" in source
    assert "permissions: {}" in source
    assert source.count(trusted_call) == 2
    assert "uses: ./.github/workflows/reusable-terraform-plan.yml" not in source
    assert source.count("github.event.pull_request.head.repo.full_name == github.repository") == 2
    assert source.count("contents: read") == 2
    assert source.count("id-token: write") == 2
    assert "needs: plan-uat" in source
    assert source.index("environment: uat") < source.index("environment: production")
    assert "reusable-terraform-deploy" not in source


def test_obsolete_oidc_workflow_can_only_probe_denials() -> None:
    source = (ROOT / ".github" / "workflows" / "aws-oidc-identity-test.yml").read_text(
        encoding="utf-8"
    )

    assert "Reject obsolete AWS OIDC workflow" in source
    assert source.count("assume-role-with-web-identity") == 1
    assert "UAT_PLAN_ROLE_ARN" in source
    assert "PRODUCTION_PLAN_ROLE_ARN" in source
    assert "UAT_DEPLOY_ROLE_ARN" in source
    assert "PRODUCTION_DEPLOY_ROLE_ARN" in source
    assert "configure-aws-credentials" not in source
    assert "terraform" not in source.lower()
