import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "infra" / "components" / "static-site"
WORKFLOW = ROOT / ".github" / "workflows" / "reusable-terraform-deploy.yml"


def _plan_summary_script() -> str:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["deploy"]["steps"]
    return next(step["run"] for step in steps if step["name"] == "Summarize fresh deployment plan")


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
        "TF_WORKSPACE": "uat",
    }
    return subprocess.run(
        ["bash", "-c", _plan_summary_script()],
        cwd=COMPONENT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )


def test_plan_summary_accepts_reviewed_configuration_changes(tmp_path: Path) -> None:
    changes = [
        _change("aws_s3_bucket.new", "create"),
        _change("aws_cloudfront_distribution.site", "update"),
        _change("aws_s3_bucket.old", "delete"),
    ]

    result = _run_gate(tmp_path, changes, plan_has_changes=True)

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "github-output").read_text(encoding="utf-8") == "mode=apply\n"
    summary = (tmp_path / "github-summary").read_text(encoding="utf-8")
    assert "aws_s3_bucket.new" in summary
    assert "aws_cloudfront_distribution.site" in summary
    assert "aws_s3_bucket.old" in summary


def test_plan_summary_accepts_an_idempotent_plan(tmp_path: Path) -> None:
    changes = [_change("aws_s3_bucket.site", "no-op")]

    result = _run_gate(tmp_path, changes, plan_has_changes=False)

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "github-output").read_text(encoding="utf-8") == "mode=no-changes\n"


@pytest.mark.parametrize(
    ("resource_changes", "plan_has_changes"),
    [
        ([], True),
        ([_change("aws_s3_bucket.site", "create")], False),
    ],
    ids=["empty-plan-reported-changed", "create-plan-reported-unchanged"],
)
def test_plan_summary_rejects_a_terraform_exit_status_mismatch(
    tmp_path: Path,
    resource_changes: list[dict[str, object]],
    plan_has_changes: bool,
) -> None:
    result = _run_gate(tmp_path, resource_changes, plan_has_changes=plan_has_changes)

    assert result.returncode != 0
    assert "Terraform exit status and the saved plan disagree" in result.stdout
