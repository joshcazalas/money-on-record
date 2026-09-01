from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "prepare-release.py"
SPEC = importlib.util.spec_from_file_location("prepare_release", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
RELEASE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = RELEASE
SPEC.loader.exec_module(RELEASE)

REVISION = "a" * 40


def _pull(number: int, impact: str) -> object:
    return RELEASE.PullRequest(
        number=number,
        title=f"Change {number}",
        url=f"https://github.com/owner/repository/pull/{number}",
        author="maintainer",
        impact=impact,
        merge_commit_sha=str(number) * 40,
    )


def test_latest_release_uses_highest_stable_semantic_version() -> None:
    previous = RELEASE.latest_stable_release(
        [
            {"tag_name": "notes", "draft": False, "prerelease": False, "immutable": True},
            {"tag_name": "v1.9.0", "draft": False, "prerelease": False, "immutable": True},
            {"tag_name": "v2.0.0", "draft": False, "prerelease": True, "immutable": True},
            {"tag_name": "v1.10.0", "draft": False, "prerelease": False, "immutable": True},
        ]
    )

    assert previous == RELEASE.PreviousRelease("v1.10.0", (1, 10, 0))


def test_mutable_previous_release_is_rejected() -> None:
    with pytest.raises(RELEASE.ReleaseError, match="is not immutable"):
        RELEASE.latest_stable_release(
            [
                {
                    "tag_name": "v1.0.0",
                    "draft": False,
                    "prerelease": False,
                    "immutable": False,
                }
            ]
        )


@pytest.mark.parametrize(
    ("previous", "impacts", "expected"),
    [
        (None, ["minor", "patch"], "v0.1.0"),
        (RELEASE.PreviousRelease("v1.2.3", (1, 2, 3)), ["patch"], "v1.2.4"),
        (RELEASE.PreviousRelease("v1.2.3", (1, 2, 3)), ["minor", "patch"], "v1.3.0"),
        (RELEASE.PreviousRelease("v1.2.3", (1, 2, 3)), ["patch", "major"], "v2.0.0"),
    ],
)
def test_release_uses_greatest_pr_impact(
    previous: object | None,
    impacts: list[str],
    expected: str,
) -> None:
    plan = RELEASE.plan_release(
        previous,
        [_pull(index, impact) for index, impact in enumerate(impacts, start=1)],
        REVISION,
    )

    assert plan.tag == expected
    assert plan.version == expected.removeprefix("v")


@pytest.mark.parametrize("labels", [[], [{"name": "minor"}, {"name": "patch"}]])
def test_pull_request_requires_exactly_one_release_label(labels: list[dict[str, str]]) -> None:
    data = {
        "number": 7,
        "title": "Release change",
        "html_url": "https://github.com/owner/repository/pull/7",
        "user": {"login": "maintainer"},
        "merged_at": "2026-08-29T00:00:00Z",
        "merge_commit_sha": REVISION,
        "base": {"ref": "main"},
        "labels": labels,
    }

    with pytest.raises(RELEASE.ReleaseError, match="exactly one release label"):
        RELEASE.pull_request_from_api(data, REVISION)


def test_release_notes_identify_every_pull_request_and_evidence() -> None:
    plan = RELEASE.plan_release(None, [_pull(3, "minor"), _pull(4, "patch")], REVISION)
    notes = RELEASE.render_notes(plan)

    assert "Money on Record v0.1.0" in notes
    assert "[#3](https://github.com/owner/repository/pull/3)" in notes
    assert "[#4](https://github.com/owner/repository/pull/4)" in notes
    assert "CycloneDX and SPDX SBOMs" in notes
    assert "GitHub artifact attestations" in notes


def test_github_api_calls_pin_endpoint_compatible_versions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[list[str]] = []

    def fake_run(
        command: list[str],
        *,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        del check
        captured.append(command)
        return subprocess.CompletedProcess(command, 0, "{}", "")

    monkeypatch.setattr(RELEASE, "run", fake_run)

    assert RELEASE.github_json("owner/repository", "releases") == {}
    assert RELEASE.github_json("owner/repository", "pulls/7") == {}
    assert "X-GitHub-Api-Version: 2026-03-10" in captured[0]
    assert "X-GitHub-Api-Version: 2022-11-28" in captured[1]


def test_direct_main_commits_after_a_release_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    direct_commit = "b" * 40

    def fake_run(
        command: list[str],
        *,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        del check
        if "merge-base" in command:
            return subprocess.CompletedProcess(command, 0, "", "")
        if "--no-merges" in command:
            return subprocess.CompletedProcess(command, 0, f"{direct_commit}\n", "")
        raise AssertionError(command)

    monkeypatch.setattr(RELEASE, "run", fake_run)

    with pytest.raises(RELEASE.ReleaseError, match="cannot supply release labels"):
        RELEASE.merged_pull_requests(
            "owner/repository",
            REVISION,
            RELEASE.PreviousRelease("v1.0.0", (1, 0, 0)),
        )
