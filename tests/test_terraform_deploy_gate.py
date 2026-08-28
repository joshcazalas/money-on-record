import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "infra" / "components" / "static-site"
WORKFLOW = ROOT / ".github" / "workflows" / "reusable-terraform-deploy.yml"

EXPECTED_RESOURCES = [
    "terraform_data.workspace_contract",
    "module.static_site[0].aws_s3_bucket_policy.site",
    "module.static_site[0].module.cdn.aws_cloudfront_distribution.this[0]",
    'module.static_site[0].module.cdn.aws_cloudfront_origin_access_control.this["site"]',
    "module.static_site[0].module.site_bucket.aws_s3_bucket.this[0]",
    "module.static_site[0].module.site_bucket.aws_s3_bucket_ownership_controls.this[0]",
    "module.static_site[0].module.site_bucket.aws_s3_bucket_public_access_block.this[0]",
    (
        "module.static_site[0].module.site_bucket."
        "aws_s3_bucket_server_side_encryption_configuration.this[0]"
    ),
    "module.static_site[0].module.site_bucket.aws_s3_bucket_versioning.this[0]",
]


def _bootstrap_gate_script() -> str:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["deploy"]["steps"]
    return next(step["run"] for step in steps if step["name"] == "Enforce bootstrap plan allowlist")


def _change(address: str, *actions: str) -> dict[str, object]:
    return {
        "address": address,
        "mode": "managed",
        "change": {"actions": list(actions)},
    }


def _run_gate(
    tmp_path: Path,
    resource_changes: list[dict[str, object]],
    *,
    plan_has_changes: bool,
) -> subprocess.CompletedProcess[str]:
    plan_json = tmp_path / "fixture-plan.json"
    plan_json.write_text(json.dumps({"resource_changes": resource_changes}), encoding="utf-8")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    terraform = fake_bin / "terraform"
    terraform.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        '[[ "$1" == "show" && "$2" == "-json" ]]\n'
        'cat "$FAKE_PLAN_JSON"\n',
        encoding="utf-8",
    )
    terraform.chmod(0o755)

    output = tmp_path / "github-output"
    summary = tmp_path / "github-summary"
    env = os.environ | {
        "FAKE_PLAN_JSON": str(plan_json),
        "GITHUB_OUTPUT": str(output),
        "GITHUB_STEP_SUMMARY": str(summary),
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "PLAN_HAS_CHANGES": str(plan_has_changes).lower(),
        "RUNNER_TEMP": str(tmp_path),
    }
    return subprocess.run(
        ["bash", "-c", _bootstrap_gate_script()],
        cwd=COMPONENT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )


def test_bootstrap_gate_accepts_the_exact_nine_resource_create_plan(tmp_path: Path) -> None:
    changes = [_change(address, "create") for address in EXPECTED_RESOURCES]

    result = _run_gate(tmp_path, changes, plan_has_changes=True)

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "github-output").read_text(encoding="utf-8") == "mode=create-nine\n"
    assert "9 additions, 0 changes, 0 destroys" in (tmp_path / "github-summary").read_text(
        encoding="utf-8"
    )


def test_bootstrap_gate_accepts_an_idempotent_plan(tmp_path: Path) -> None:
    changes = [_change(address, "no-op") for address in EXPECTED_RESOURCES]

    result = _run_gate(tmp_path, changes, plan_has_changes=False)

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "github-output").read_text(encoding="utf-8") == "mode=no-changes\n"


@pytest.mark.parametrize(
    "resource_changes",
    [
        [_change(address, "create") for address in EXPECTED_RESOURCES[:-1]],
        [
            *[_change(address, "create") for address in EXPECTED_RESOURCES],
            _change("aws_s3_object.unreviewed", "create"),
        ],
        [
            *[_change(address, "create") for address in EXPECTED_RESOURCES[1:]],
            _change(EXPECTED_RESOURCES[0], "update"),
        ],
        [
            *[_change(address, "create") for address in EXPECTED_RESOURCES[1:]],
            _change(EXPECTED_RESOURCES[0], "delete"),
        ],
        [
            *[_change(address, "create") for address in EXPECTED_RESOURCES[1:]],
            _change(EXPECTED_RESOURCES[0], "delete", "create"),
        ],
    ],
    ids=["missing-resource", "extra-resource", "update", "delete", "replacement"],
)
def test_bootstrap_gate_rejects_any_unreviewed_resource_action(
    tmp_path: Path,
    resource_changes: list[dict[str, object]],
) -> None:
    result = _run_gate(tmp_path, resource_changes, plan_has_changes=True)

    assert result.returncode != 0
    assert "does not match the reviewed UAT bootstrap allowlist" in result.stdout


@pytest.mark.parametrize(
    ("resource_changes", "plan_has_changes"),
    [
        ([], True),
        ([_change(address, "create") for address in EXPECTED_RESOURCES], False),
    ],
    ids=["empty-plan-reported-changed", "create-plan-reported-unchanged"],
)
def test_bootstrap_gate_rejects_a_terraform_exit_status_mismatch(
    tmp_path: Path,
    resource_changes: list[dict[str, object]],
    plan_has_changes: bool,
) -> None:
    result = _run_gate(tmp_path, resource_changes, plan_has_changes=plan_has_changes)

    assert result.returncode != 0
    assert "Terraform exit status and the saved plan disagree" in result.stdout
