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


def test_reusable_terraform_workflows_are_fail_closed_bootstraps() -> None:
    workflows = (
        ROOT / ".github" / "workflows" / "reusable-terraform-plan.yml",
        ROOT / ".github" / "workflows" / "reusable-terraform-deploy.yml",
    )

    for workflow in workflows:
        source = workflow.read_text(encoding="utf-8")
        assert "workflow_call:" in source
        assert "permissions: {}" in source
        assert "exit 1" in source
        assert "terraform apply" not in source
