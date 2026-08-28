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
    assert "terraform init -input=false -lockfile=readonly -no-color" in source
    assert "terraform plan \\" in source
    assert "-lock=false" in source
    assert "-detailed-exitcode" in source
    assert "terraform workspace new" not in source
    assert "terraform workspace select" not in source
    assert "terraform apply" not in source
    assert "upload-artifact" not in source


def test_reusable_terraform_deploy_remains_fail_closed() -> None:
    source = (ROOT / ".github" / "workflows" / "reusable-terraform-deploy.yml").read_text(
        encoding="utf-8"
    )

    assert "workflow_call:" in source
    assert "permissions: {}" in source
    assert "exit 1" in source
    assert "terraform apply" not in source


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
