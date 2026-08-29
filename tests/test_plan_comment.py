from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
RENDERER_PATH = REPOSITORY_ROOT / "scripts" / "render-plan-comment.py"
SPEC = importlib.util.spec_from_file_location("render_plan_comment", RENDERER_PATH)
assert SPEC is not None and SPEC.loader is not None
RENDERER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = RENDERER
SPEC.loader.exec_module(RENDERER)


def test_plan_json_is_scoped_to_environment() -> None:
    plan = {
        "resource_changes": [
            {
                "address": "aws_s3_bucket.site",
                "change": {"actions": ["create"]},
            },
            {
                "address": "data.aws_caller_identity.current",
                "change": {"actions": ["read"]},
            },
            {
                "address": "aws_s3_bucket.no_change",
                "change": {"actions": ["no-op"]},
            },
        ]
    }
    completed = subprocess.run(
        [
            "jq",
            "--arg",
            "environment",
            "uat",
            "-f",
            str(REPOSITORY_ROOT / "scripts" / "summarize-plan.jq"),
        ],
        input=json.dumps(plan),
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(completed.stdout) == [
        {"address": "aws_s3_bucket.site", "actions": ["create"], "scope": "uat"}
    ]


def test_runner_writes_sanitized_environment_artifact(tmp_path: Path) -> None:
    source = tmp_path / "source"
    root = source / "infra" / "components" / "static-site"
    root.mkdir(parents=True)
    (root / "backend.tf").write_text('terraform { backend "s3" {} }\n', encoding="utf-8")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_terraform = fake_bin / "terraform"
    fake_terraform.write_text(
        """#!/usr/bin/env bash
set -euo pipefail

command_name=""
for argument in "$@"; do
  case "$argument" in
    init|workspace|validate|plan|show)
      command_name="$argument"
      break
      ;;
  esac
done

case "$command_name" in
  init)
    echo "Initialized."
    ;;
  workspace)
    echo "$TF_WORKSPACE"
    ;;
  validate)
    echo "Success! The configuration is valid."
    ;;
  plan)
    for argument in "$@"; do
      case "$argument" in
        -out=*)
          : >"${argument#-out=}"
          ;;
      esac
    done
    echo "Plan: 1 to add, 0 to change, 0 to destroy."
    exit 2
    ;;
  show)
    if [[ " $* " == *" -json "* ]]; then
      printf '%s\n' \
        '{"resource_changes":[{"address":"aws_s3_bucket.site",'\
'"change":{"actions":["create"]}}]}'
    else
      echo "+ aws_s3_bucket.site"
    fi
    ;;
  *)
    exit 64
    ;;
esac
""",
        encoding="utf-8",
    )
    fake_terraform.chmod(0o755)
    results = tmp_path / "results"
    environment = os.environ.copy()
    environment["PATH"] = f"{fake_bin}:{environment['PATH']}"
    environment["TF_WORKSPACE"] = "uat"

    subprocess.run(
        [
            "bash",
            str(REPOSITORY_ROOT / "scripts" / "run-terraform-plan.sh"),
            str(source),
            "uat",
            "false",
            str(results),
        ],
        check=True,
        capture_output=True,
        env=environment,
        text=True,
    )

    metadata = json.loads((results / "uat" / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["status"] == "success"
    assert metadata["exit_code"] == 2
    assert metadata["overall"] == {"add": 1, "change": 0, "destroy": 0}
    assert metadata["scopes"] == [{"name": "uat", "add": 1, "change": 0, "destroy": 0}]
    assert (results / "uat" / "plan.txt").read_text(encoding="utf-8") == ("+ aws_s3_bucket.site\n")
    assert not list(results.rglob("*.tfplan"))
    assert list(results.rglob("*.json")) == [results / "uat" / "metadata.json"]


def _write_result(
    directory: Path,
    environment: str,
    counts: tuple[int, int, int],
    plan: str,
    status: str = "success",
) -> None:
    result_directory = directory / environment
    result_directory.mkdir()
    metadata = {
        "root": "infra/components/static-site",
        "slug": environment,
        "status": status,
        "phase": "plan",
        "exit_code": 0 if counts == (0, 0, 0) else 2,
        "overall": {"add": counts[0], "change": counts[1], "destroy": counts[2]},
        "scopes": [
            {
                "name": environment,
                "add": counts[0],
                "change": counts[1],
                "destroy": counts[2],
            }
        ],
    }
    (result_directory / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    (result_directory / "plan.txt").write_text(plan, encoding="utf-8")


def _complete_results(directory: Path, production_plan: str = "No changes.") -> None:
    _write_result(directory, "production", (1, 0, 0), production_plan)
    _write_result(directory, "uat", (0, 1, 0), "~ aws_cloudfront_distribution.site")


def test_comment_is_ordered_colored_and_linked(tmp_path: Path) -> None:
    _complete_results(tmp_path, "+ aws_s3_bucket.site\n- aws_s3_bucket.old")
    comment = RENDERER.render_comment(tmp_path, "owner/repository", "1234")

    assert comment.startswith(RENDERER.MARKER)
    assert comment.index("### Production") < comment.index("### UAT")
    assert "| Production | 1 to add, 0 to change, 0 to destroy. |" in comment
    assert "| UAT | 0 to add, 1 to change, 0 to destroy. |" in comment
    assert "+ + aws_s3_bucket.site" in comment
    assert "- - aws_s3_bucket.old" in comment
    assert "! ! aws_cloudfront_distribution.site" in comment
    assert "[View CI run](https://github.com/owner/repository/actions/runs/1234)" in comment


def test_missing_artifact_is_reported_as_failure(tmp_path: Path) -> None:
    _write_result(tmp_path, "production", (0, 0, 0), "No changes.")
    comment = RENDERER.render_comment(tmp_path, "owner/repository", "1234")

    assert "| UAT | Plan failed. Review the CI run. |" in comment
    assert "The plan result artifact is missing." in comment


def test_large_plan_is_deterministically_truncated(tmp_path: Path) -> None:
    _complete_results(tmp_path, "+ resource change\n" * 10_000)
    first = RENDERER.render_comment(tmp_path, "owner/repository", "1234")
    second = RENDERER.render_comment(tmp_path, "owner/repository", "1234")

    assert first == second
    assert len(first) <= RENDERER.MAX_COMMENT_LENGTH
    assert RENDERER.TRUNCATION_MESSAGE in first
    assert "### Production" in first
    assert "### UAT" in first


@pytest.mark.parametrize("status", ["unexpected", ""])
def test_invalid_artifact_status_fails_closed(tmp_path: Path, status: str) -> None:
    _write_result(tmp_path, "production", (0, 0, 0), "No changes.", status=status)
    _write_result(tmp_path, "uat", (0, 0, 0), "No changes.")

    comment = RENDERER.render_comment(tmp_path, "owner/repository", "1234")

    assert "| Production | Plan failed. Review the CI run. |" in comment
    assert "artifact status is invalid" in comment
