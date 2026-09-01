import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "infra" / "components" / "static-site"


def _quoted_assignment(source: str, name: str) -> str:
    match = re.search(rf"^\s*{re.escape(name)}\s*=\s*\"([^\"]+)\"\s*$", source, re.MULTILINE)
    assert match is not None, f"missing quoted backend assignment: {name}"
    return match.group(1)


def _assert_native_terraform_exit_contract(source: str) -> None:
    workflow = yaml.safe_load(source)
    setup_steps = [
        step
        for job in workflow["jobs"].values()
        for step in job["steps"]
        if step.get("uses", "").startswith("hashicorp/setup-terraform@")
    ]

    assert len(setup_steps) == 1
    assert setup_steps[0]["with"]["terraform_wrapper"] is False
    assert "id" not in setup_steps[0]
    assert not re.search(r"steps\.[^.}\s]+\.outputs\.(?:exitcode|stdout|stderr)", source)


def test_centralized_backend_uses_workspace_keys() -> None:
    backend = (COMPONENT / "backend.tf").read_text(encoding="utf-8")
    component = (COMPONENT / "main.tf").read_text(encoding="utf-8")

    assert _quoted_assignment(backend, "bucket") == ("joshcazalas-deployment-tfstate-245459924498")
    assert _quoted_assignment(backend, "region") == "us-east-1"
    assert re.search(r"^\s*encrypt\s*=\s*true\s*$", backend, re.MULTILINE)
    assert re.search(r"^\s*use_lockfile\s*=\s*true\s*$", backend, re.MULTILINE)
    assert re.search(
        r'^\s*allowed_account_ids\s*=\s*\["245459924498"\]\s*$',
        backend,
        re.MULTILINE,
    )

    assert _quoted_assignment(backend, "key") == "terraform.tfstate"
    assert _quoted_assignment(backend, "workspace_key_prefix") == ("money-on-record/static-site")
    assert "terraform.workspace" in component
    assert (
        'state_object_key     = "money-on-record/static-site/'
        '${terraform.workspace}/terraform.tfstate"' in component
    )


def test_environment_roots_were_replaced_by_one_component() -> None:
    assert COMPONENT.is_dir()
    assert not (ROOT / "infra" / "environments").exists()


def test_workspace_configuration_binds_each_account_and_role() -> None:
    source = (COMPONENT / "main.tf").read_text(encoding="utf-8")
    variables = (COMPONENT / "variables.tf").read_text(encoding="utf-8")

    assert 'aws_account_id      = "732006412638"' in source
    assert 'aws_account_id      = "134604497564"' in source
    assert "allowed_account_ids = [local.aws_account_id]" in source
    assert "MoneyOnRecordTerraform(Plan|Deploy)" in variables
    assert 'resource "terraform_data" "workspace_contract"' in source
    assert "contains(local.allowed_workload_role_arns" in source


def test_ci_runs_for_pull_requests_and_manual_requests_only() -> None:
    source = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert re.search(r"^  pull_request:$", source, re.MULTILINE)
    assert re.search(r"^  workflow_dispatch:$", source, re.MULTILINE)
    assert not re.search(r"^  push:$", source, re.MULTILINE)


def test_reusable_terraform_plan_is_read_only_and_workspace_bound() -> None:
    source = (ROOT / ".github" / "workflows" / "reusable-terraform-plan.yml").read_text(
        encoding="utf-8"
    )
    runner = (ROOT / "scripts" / "run-terraform-plan.sh").read_text(encoding="utf-8")

    assert "workflow_call:" in source
    assert "contents: read" in source
    assert "id-token: write" in source
    assert "CALLER_REPOSITORY" in source
    assert "TF_WORKSPACE: ${{ inputs.environment }}" in source
    assert "STATE_BUCKET: ${{ vars.TF_STATE_BUCKET }}" in source
    assert (
        "STATE_KEY: money-on-record/static-site/${{ inputs.environment }}/terraform.tfstate"
        in source
    )
    assert "Check out pull-request source" in source
    assert "Check out trusted planning code" in source
    assert source.count("persist-credentials: false") == 3
    assert 'bash "$GITHUB_WORKSPACE/trusted/scripts/run-terraform-plan.sh"' in source
    assert 'terraform -chdir="$terraform_root" init' in runner
    assert "-backend-config=use_lockfile=false" in runner
    assert "head-object" in source
    assert "Not Found|NoSuchKey" in source
    assert 'export TF_WORKSPACE="$environment"' in runner
    assert "-backend=false" in runner
    assert "-refresh=false" in runner
    assert "-lock=false" in runner
    assert "-detailed-exitcode" in runner
    assert "plan_exit_code=$?" in runner
    assert "terraform apply" not in runner
    assert "name: terraform-plan-${{ inputs.environment }}" in source
    assert "retention-days: 7" in source
    assert "continue-on-error" not in source
    assert "if: always()" not in source
    assert "has_changes" not in source
    assert "Verify plan-hub isolation" not in source
    assert "Verify deployment hubs reject" not in source
    _assert_native_terraform_exit_contract(source)


def test_reusable_terraform_deploy_is_environment_and_release_bound() -> None:
    source = (ROOT / ".github" / "workflows" / "reusable-terraform-deploy.yml").read_text(
        encoding="utf-8"
    )

    assert "workflow_call:" in source
    assert source.count("contents: read") == 1
    assert source.count("id-token: write") == 1
    assert "environment: ${{ inputs.environment }}" in source
    assert "environment must be uat or production" in source
    assert 'CALLER_EVENT" == "push"' in source
    assert 'CALLER_EVENT" == "workflow_dispatch"' in source
    assert "pull_request" not in source
    assert "cancel-in-progress: false" in source
    assert "persist-credentials: false" in source
    assert "ref: ${{ inputs.revision }}" in source
    assert "allowed-account-ids: ${{ vars.AWS_DEPLOYMENT_ACCOUNT_ID }}" in source
    assert 'gh attestation verify "$archive"' in source
    assert "terraform init" in source
    assert "-lockfile=readonly" in source
    assert "-lock-timeout=5m" in source
    assert "TF_WORKSPACE: ${{ inputs.environment }}" in source
    assert '-out="$RUNNER_TEMP/money-on-record-${TF_WORKSPACE}.tfplan"' in source
    assert "terraform apply" in source
    assert '"$RUNNER_TEMP/money-on-record-${TF_WORKSPACE}.tfplan"' in source
    assert "continue-on-error" not in source
    assert "terraform show" not in source
    assert "Smoke-test" not in source
    assert "Verify deployment-hub isolation" not in source
    assert "authorize:" not in source
    assert "terraform destroy" not in source
    assert "upload-artifact" not in source
    assert "-lock=false" not in source
    assert "use_lockfile=false" not in source
    _assert_native_terraform_exit_contract(source)


def test_main_push_deploys_uat_and_manual_recovery_remains_available() -> None:
    source = (ROOT / ".github" / "workflows" / "terraform-deploy-uat.yml").read_text(
        encoding="utf-8"
    )
    trusted_call = (
        "uses: joshcazalas/money-on-record/.github/workflows/reusable-terraform-deploy.yml@main"
    )

    assert "workflow_dispatch:" in source
    assert "confirm_uat_deployment:" in source
    assert "default: false" in source
    assert "push:" in source
    assert "branches: [main]" in source
    assert "if: github.event_name == 'push' || inputs.confirm_uat_deployment" in source
    assert "permissions: {}" in source
    assert "contents: read" in source
    assert "id-token: write" in source
    assert source.count(trusted_call) == 1
    assert "environment: uat" in source
    assert "revision: ${{ github.sha }}" in source
    assert "pull_request:" not in source
    assert "schedule:" not in source
    assert "environment: production" not in source


def test_production_deploy_accepts_only_an_immutable_release() -> None:
    source = (ROOT / ".github" / "workflows" / "terraform-deploy-production.yml").read_text(
        encoding="utf-8"
    )
    trusted_call = (
        "uses: joshcazalas/money-on-record/.github/workflows/reusable-terraform-deploy.yml@main"
    )

    assert "workflow_call:" in source
    assert "workflow_dispatch:" in source
    assert "confirm_production_deployment:" in source
    assert "default: false" in source
    assert "Resolve immutable release" in source
    assert ".draft == false and .prerelease == false and .immutable == true" in source
    assert "X-GitHub-Api-Version: 2026-03-10" in source
    assert "The release target is not an exact commit SHA" in source
    assert "The release target changed after release creation" in source
    assert source.count(trusted_call) == 1
    assert "environment: production" in source
    assert "environment: uat" not in source
    assert "pull_request:" not in source
    assert "push:" not in source


def test_release_is_manual_attested_and_optionally_deploys_production() -> None:
    source = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    production_call = (
        "uses: joshcazalas/money-on-record/.github/workflows/terraform-deploy-production.yml@main"
    )

    assert "workflow_dispatch:" in source
    assert "deploy_production:" in source
    assert "default: false" in source
    assert "pull_request:" not in source
    assert "push:" not in source
    assert "refs/heads/main" in source
    assert "Releases require Josh's immutable actor ID" in source
    assert "RELEASE_IMMUTABILITY_ENABLED" in source
    assert "scripts/prepare-release.py" in source
    assert "uv export" in source
    assert "--format cyclonedx1.5" in source
    assert "uv build" in source
    assert "mor-l0 build-site" in source
    assert "money-on-record-site-${RELEASE_VERSION}.zip" in source
    assert "money-on-record-site-${RELEASE_VERSION}.zip.sha256" in source
    assert "anchore/sbom-action@3ad7283483fc7af8ff2b4ea19663c2d5ca935e26" in source
    assert source.count("actions/attest@1e69f48acb82d1966a394da916b4c1698aa569d6") == 3
    assert "dependency-snapshot: true" in source
    assert "cd release/publish" in source
    assert "sha256sum -- * >../SHA256SUMS" in source
    assert "mv release/SHA256SUMS release/publish/SHA256SUMS" in source
    assert 'gh release create "$RELEASE_TAG"' in source
    assert ".immutable == true" in source
    assert "X-GitHub-Api-Version: 2026-03-10" in source
    assert "if: inputs.deploy_production" in source
    assert source.count(production_call) == 1
    assert not (ROOT / ".github" / "workflows" / "terraform-apply.yml").exists()


def test_pull_request_plans_call_only_the_trusted_main_workflow() -> None:
    source = (ROOT / ".github" / "workflows" / "terraform-plan.yml").read_text(encoding="utf-8")
    trusted_call = (
        "uses: joshcazalas/money-on-record/.github/workflows/reusable-terraform-plan.yml@main"
    )

    assert "pull_request:" in source
    assert "permissions: {}" in source
    assert source.count(trusted_call) == 1
    assert "uses: ./.github/workflows/reusable-terraform-plan.yml" not in source
    assert source.count("github.event.pull_request.head.repo.full_name == github.repository") == 2
    assert source.count("contents: read") == 2
    assert source.count("id-token: write") == 1
    assert "actions: read" in source
    assert "pull-requests: write" in source
    assert "environment: [uat, production]" in source
    assert "fail-fast: false" in source
    assert "needs: plan" in source
    assert "actions/download-artifact@" in source
    assert "trusted/scripts/render-plan-comment.py" in source
    assert "trusted/scripts/publish-plan-comment.sh" in source
    assert "continue-on-error" not in source
    assert "if: always()" not in source
    assert "reusable-terraform-deploy" not in source


def test_no_runtime_oidc_denial_probe_workflow_exists() -> None:
    assert not (ROOT / ".github" / "workflows" / "aws-oidc-identity-test.yml").exists()
