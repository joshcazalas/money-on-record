#!/usr/bin/env python3
"""Render sanitized Terraform plan results as one bounded PR comment."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path

MARKER = "<!-- money-on-record-terraform-plan -->"
MAX_COMMENT_LENGTH = 60_000
TRUNCATION_MESSAGE = "Plan detail truncated. Use the CI-run link for the complete log."

ROOTS = (
    ("infra/components/static-site", "production", ("production",)),
    ("infra/components/static-site", "uat", ("uat",)),
)
SCOPES = (
    ("production", "Production"),
    ("uat", "UAT"),
)


@dataclass(frozen=True)
class ScopeResult:
    name: str
    add: int = 0
    change: int = 0
    destroy: int = 0


@dataclass(frozen=True)
class RootResult:
    root: str
    slug: str
    status: str
    phase: str
    exit_code: int
    overall: ScopeResult
    scopes: dict[str, ScopeResult]
    plan: str


def summary(add: int, change: int, destroy: int, status: str = "success") -> str:
    if status != "success":
        return "Plan failed. Review the CI run."
    if add == 0 and change == 0 and destroy == 0:
        return "No changes. Your infrastructure matches the configuration."
    return f"{add} to add, {change} to change, {destroy} to destroy."


def failed_root(root: str, slug: str, scopes: tuple[str, ...], message: str) -> RootResult:
    empty_scopes = {scope: ScopeResult(scope) for scope in scopes}
    return RootResult(
        root=root,
        slug=slug,
        status="failed",
        phase="artifact",
        exit_code=1,
        overall=ScopeResult("overall"),
        scopes=empty_scopes,
        plan=message,
    )


def load_root(results_directory: Path, root: str, slug: str, scopes: tuple[str, ...]) -> RootResult:
    result_directory = results_directory / slug
    metadata_path = result_directory / "metadata.json"
    plan_path = result_directory / "plan.txt"

    if not metadata_path.is_file() or not plan_path.is_file():
        return failed_root(root, slug, scopes, "The plan result artifact is missing.")

    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        plan = plan_path.read_text(encoding="utf-8")
        if metadata["root"] != root or metadata["slug"] != slug:
            raise ValueError("artifact identity does not match its expected root")

        overall_data = metadata["overall"]
        overall = ScopeResult(
            "overall",
            int(overall_data["add"]),
            int(overall_data["change"]),
            int(overall_data["destroy"]),
        )
        loaded_scopes = {
            item["name"]: ScopeResult(
                item["name"], int(item["add"]), int(item["change"]), int(item["destroy"])
            )
            for item in metadata["scopes"]
        }
        if set(loaded_scopes) != set(scopes):
            raise ValueError("artifact scopes do not match their expected root")

        status = str(metadata["status"])
        if status not in {"success", "failed"}:
            raise ValueError("artifact status is invalid")

        return RootResult(
            root=root,
            slug=slug,
            status=status,
            phase=str(metadata["phase"]),
            exit_code=int(metadata["exit_code"]),
            overall=overall,
            scopes=loaded_scopes,
            plan=plan,
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        return failed_root(root, slug, scopes, f"The plan result artifact is invalid: {error}")


def aggregate_scope(scope: str, roots: list[RootResult]) -> ScopeResult:
    values = [result.scopes[scope] for result in roots if scope in result.scopes]
    return ScopeResult(
        scope,
        sum(value.add for value in values),
        sum(value.change for value in values),
        sum(value.destroy for value in values),
    )


def scope_status(scope: str, roots: list[RootResult]) -> str:
    failed = any(scope in root.scopes and root.status != "success" for root in roots)
    return "failed" if failed else "success"


def diff_plan(plan: str) -> str:
    rendered: list[str] = []
    for line in plan.rstrip().splitlines():
        stripped = line.lstrip()
        if stripped.startswith(("+", "-", "~")):
            marker = "!" if stripped[0] == "~" else stripped[0]
            index = len(line) - len(stripped)
            presentation = line[:index] + marker + stripped[1:]
            rendered.append(f"{marker} {presentation}")
        else:
            rendered.append(f"  {line}")
    return "\n".join(rendered)


def fence_for(text: str) -> str:
    longest_literal_run = max((len(run) for run in re.findall(r"`+", text)), default=0)
    return "`" * max(4, longest_literal_run + 1)


def truncate_body(body: str, limit: int) -> str:
    if len(body) <= limit:
        return body

    lines = body.splitlines()
    fence_index = next(
        (
            index
            for index, line in enumerate(lines)
            if line.endswith("diff") and set(line[:-4]) == {"`"}
        ),
        None,
    )
    if fence_index is None:
        return ""

    fence = lines[fence_index][:-4]
    prefix = "\n".join(lines[: fence_index + 1]) + "\n"
    suffix = f"\n{fence}\n\n_\u202f{TRUNCATION_MESSAGE}_\n"
    available = limit - len(prefix) - len(suffix)
    if available <= 0:
        return ""

    plan_text = "\n".join(lines[fence_index + 1 : -1])
    return prefix + plan_text[:available].rstrip() + suffix


def detail_parts(root: RootResult, scope: str) -> tuple[str, str, str]:
    counts = root.scopes[scope]
    status_summary = summary(counts.add, counts.change, counts.destroy, root.status)
    opening = f"<details>\n<summary><code>{root.root}</code> — {status_summary}</summary>\n\n"

    plan = diff_plan(root.plan)
    fence = fence_for(plan)
    body = f"{fence}diff\n{plan}\n{fence}\n"
    closing = "\n</details>"
    return opening, body, closing


def render_comment(results_directory: Path, repository: str, run_id: str) -> str:
    roots = [load_root(results_directory, root, slug, scopes) for root, slug, scopes in ROOTS]

    table_rows = []
    for scope, label in SCOPES:
        counts = aggregate_scope(scope, roots)
        table_rows.append(
            f"| {label} | "
            f"{summary(counts.add, counts.change, counts.destroy, scope_status(scope, roots))} |"
        )

    header = "\n".join(
        (
            MARKER,
            "## Terraform Plan - post-merge preview",
            "",
            "What `terraform apply` will do when this PR merges.",
            "",
            "| Env | Plan |",
            "|---|---|",
            *table_rows,
            "",
        )
    )
    footer = f"\n\n[View CI run](https://github.com/{repository}/actions/runs/{run_id})"

    sections: list[tuple[str, list[tuple[str, str, str]]]] = []
    for scope, label in SCOPES:
        details = [detail_parts(root, scope) for root in roots if scope in root.scopes]
        sections.append((f"### {label}\n\n", details))

    minimal_body = f"_\u202f{TRUNCATION_MESSAGE}_\n"
    fixed_length = len(header) + len(footer)
    for section_header, details in sections:
        fixed_length += len(section_header)
        fixed_length += sum(
            len(opening) + len(minimal_body) + len(closing) + 2 for opening, _, closing in details
        )

    if fixed_length > MAX_COMMENT_LENGTH:
        raise ValueError("comment summaries exceed the configured GitHub comment limit")

    remaining = MAX_COMMENT_LENGTH - fixed_length
    rendered_sections: list[str] = []
    for section_header, details in sections:
        rendered_details: list[str] = []
        for opening, body, closing in details:
            full_increment = len(body) - len(minimal_body)
            if full_increment <= remaining:
                selected_body = body
                remaining -= full_increment
            elif remaining > 0:
                selected_body = truncate_body(body, len(minimal_body) + remaining)
                if selected_body:
                    remaining -= max(0, len(selected_body) - len(minimal_body))
                else:
                    selected_body = minimal_body
            else:
                selected_body = minimal_body
            rendered_details.append(opening + selected_body + closing)
        rendered_sections.append(section_header + "\n\n".join(rendered_details))

    comment = header + "\n" + "\n\n".join(rendered_sections) + footer
    if len(comment) > MAX_COMMENT_LENGTH:
        raise AssertionError("rendered comment exceeds the configured limit")
    return comment


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("results_directory", type=Path)
    parser.add_argument("output_file", type=Path)
    parser.add_argument("repository")
    parser.add_argument("run_id")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    comment = render_comment(args.results_directory, args.repository, args.run_id)
    args.output_file.write_text(comment, encoding="utf-8")


if __name__ == "__main__":
    main()
