#!/usr/bin/env python3
"""Calculate the next release from merged pull-request labels."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

SEMVER = re.compile(r"^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
MERGED_PR = re.compile(r"\(#([1-9][0-9]*)\)$")
REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
COMMIT_SHA = re.compile(r"^[0-9a-f]{40}$")
IMPACT_ORDER = {"patch": 0, "minor": 1, "major": 2}
GITHUB_PULL_API_VERSION = "2022-11-28"
GITHUB_RELEASE_API_VERSION = "2026-03-10"


class ReleaseError(RuntimeError):
    """Release inputs do not satisfy the repository contract."""


@dataclass(frozen=True)
class PreviousRelease:
    tag: str
    version: tuple[int, int, int]


@dataclass(frozen=True)
class PullRequest:
    number: int
    title: str
    url: str
    author: str
    impact: str
    merge_commit_sha: str


@dataclass(frozen=True)
class ReleasePlan:
    previous_tag: str | None
    impact: str
    version: str
    tag: str
    revision: str
    pull_requests: tuple[PullRequest, ...]


def parse_semver(tag: str) -> tuple[int, int, int] | None:
    match = SEMVER.fullmatch(tag)
    if match is None:
        return None
    major, minor, patch = match.groups()
    return int(major), int(minor), int(patch)


def latest_stable_release(releases: list[dict[str, Any]]) -> PreviousRelease | None:
    candidates: list[tuple[tuple[int, int, int], dict[str, Any]]] = []
    for release in releases:
        version = parse_semver(str(release.get("tag_name", "")))
        if version is None or release.get("draft") is True or release.get("prerelease") is True:
            continue
        candidates.append((version, release))

    if not candidates:
        return None

    version, release = max(candidates, key=lambda item: item[0])
    if release.get("immutable") is not True:
        raise ReleaseError(f"previous release {release['tag_name']} is not immutable")
    return PreviousRelease(str(release["tag_name"]), version)


def next_version(previous: tuple[int, int, int], impact: str) -> tuple[int, int, int]:
    major, minor, patch = previous
    if impact == "major":
        return major + 1, 0, 0
    if impact == "minor":
        return major, minor + 1, 0
    if impact == "patch":
        return major, minor, patch + 1
    raise ReleaseError(f"unrecognized release impact: {impact}")


def pull_request_from_api(data: dict[str, Any], merge_commit_sha: str) -> PullRequest:
    if data.get("merged_at") is None or data.get("merge_commit_sha") != merge_commit_sha:
        raise ReleaseError(
            f"pull request #{data.get('number', '?')} does not own {merge_commit_sha}"
        )
    if data.get("base", {}).get("ref") != "main":
        raise ReleaseError(f"pull request #{data.get('number', '?')} did not merge to main")

    release_labels = sorted(
        {
            str(label.get("name"))
            for label in data.get("labels", [])
            if label.get("name") in IMPACT_ORDER
        }
    )
    if len(release_labels) != 1:
        raise ReleaseError(
            f"pull request #{data.get('number', '?')} must have exactly one release label; "
            f"found {release_labels}"
        )

    number = int(data["number"])
    title = " ".join(str(data["title"]).split())
    author = str(data.get("user", {}).get("login") or "unknown")
    return PullRequest(
        number=number,
        title=title,
        url=str(data["html_url"]),
        author=author,
        impact=release_labels[0],
        merge_commit_sha=merge_commit_sha,
    )


def plan_release(
    previous: PreviousRelease | None,
    pull_requests: list[PullRequest],
    revision: str,
) -> ReleasePlan:
    if not COMMIT_SHA.fullmatch(revision):
        raise ReleaseError("release revision must be an exact lowercase commit SHA")
    if not pull_requests:
        raise ReleaseError("no merged pull requests exist since the previous release")

    impact = max((pull.impact for pull in pull_requests), key=IMPACT_ORDER.__getitem__)
    previous_version = previous.version if previous is not None else (0, 0, 0)
    version_parts = next_version(previous_version, impact)
    version = ".".join(str(part) for part in version_parts)
    return ReleasePlan(
        previous_tag=previous.tag if previous is not None else None,
        impact=impact,
        version=version,
        tag=f"v{version}",
        revision=revision,
        pull_requests=tuple(pull_requests),
    )


def render_notes(plan: ReleasePlan) -> str:
    previous = plan.previous_tag or "initial release"
    lines = [
        f"# Money on Record {plan.tag}",
        "",
        f"Release impact: **{plan.impact}**  ",
        f"Previous release: **{previous}**  ",
        f"Source revision: `{plan.revision}`",
        "",
        "## Merged pull requests",
        "",
    ]
    lines.extend(
        f"- [#{pull.number}]({pull.url}) {pull.title} "
        f"— `{pull.impact}` by [@{pull.author}](https://github.com/{pull.author})"
        for pull in plan.pull_requests
    )
    lines.extend(
        (
            "",
            "## Verification",
            "",
            "Release assets include SHA-256 checksums, CycloneDX and SPDX SBOMs, "
            "and Sigstore-backed GitHub artifact attestations.",
            "",
        )
    )
    return "\n".join(lines)


def run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    if check and completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise ReleaseError(f"command failed ({' '.join(command)}): {detail}")
    return completed


def github_json(repository: str, endpoint: str, *, paginate: bool = False) -> Any:
    api_version = (
        GITHUB_PULL_API_VERSION if endpoint.startswith("pulls/") else GITHUB_RELEASE_API_VERSION
    )
    command = ["gh", "api", "-H", f"X-GitHub-Api-Version: {api_version}"]
    if paginate:
        command.extend(("--paginate", "--slurp"))
    command.append(f"repos/{repository}/{endpoint}")
    value = json.loads(run(command).stdout)
    if paginate:
        return [item for page in value for item in page]
    return value


def merged_pull_requests(
    repository: str,
    revision: str,
    previous: PreviousRelease | None,
) -> list[PullRequest]:
    if previous is not None:
        ancestor = run(["git", "merge-base", "--is-ancestor", previous.tag, revision], check=False)
        if ancestor.returncode != 0:
            raise ReleaseError(f"previous release {previous.tag} is not an ancestor of {revision}")
        revision_range = f"{previous.tag}..{revision}"
        direct_commits = run(
            ["git", "rev-list", "--first-parent", "--no-merges", "--reverse", revision_range]
        ).stdout.splitlines()
        if direct_commits:
            raise ReleaseError(
                "main contains direct commits after the previous release; "
                f"they cannot supply release labels: {direct_commits}"
            )
    else:
        revision_range = revision

    commits = run(
        ["git", "rev-list", "--first-parent", "--merges", "--reverse", revision_range]
    ).stdout.splitlines()
    pulls: list[PullRequest] = []
    seen_numbers: set[int] = set()
    for commit in commits:
        subject = run(["git", "show", "--no-patch", "--format=%s", commit]).stdout.strip()
        match = MERGED_PR.search(subject)
        if match is None:
            raise ReleaseError(f"merge commit {commit} does not identify its pull request")
        number = int(match.group(1))
        if number in seen_numbers:
            raise ReleaseError(f"pull request #{number} appears more than once in release history")
        seen_numbers.add(number)
        data = github_json(repository, f"pulls/{number}")
        pulls.append(pull_request_from_api(data, commit))
    return pulls


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--notes", required=True, type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not REPOSITORY.fullmatch(args.repository):
        raise ReleaseError("repository must have the form owner/name")
    if not COMMIT_SHA.fullmatch(args.revision):
        raise ReleaseError("revision must be an exact lowercase commit SHA")

    releases = github_json(args.repository, "releases?per_page=100", paginate=True)
    previous = latest_stable_release(releases)
    pulls = merged_pull_requests(args.repository, args.revision, previous)
    plan = plan_release(previous, pulls, args.revision)

    if any(release.get("tag_name") == plan.tag for release in releases):
        raise ReleaseError(f"release {plan.tag} already exists")
    if (
        run(
            ["git", "show-ref", "--verify", "--quiet", f"refs/tags/{plan.tag}"], check=False
        ).returncode
        == 0
    ):
        raise ReleaseError(f"tag {plan.tag} already exists without a published release")

    args.output.write_text(json.dumps(asdict(plan), indent=2) + "\n", encoding="utf-8")
    args.notes.write_text(render_notes(plan), encoding="utf-8")


if __name__ == "__main__":
    main()
