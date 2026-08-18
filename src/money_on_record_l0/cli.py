from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from .acquire import (
    AcquisitionError,
    acquire_csv,
    freeze_metadata,
    project_root,
    verify_artifacts,
)
from .audit import run_identity_audit
from .candidates import CandidateError, generate_candidates
from .contracts import ContractError, Inventory, load_inventory
from .dictionary import write_field_dictionary
from .fixtures import create_redacted_fixture
from .privacy import PublicSchemaError, scan_public_csv
from .profile import profile_csv, summarize_profiles
from .review import ReviewError, initialize_review, validate_review, write_review_summary
from .versioned import VersionedDataError, validate_versioned_data


def _add_selection(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("sources", nargs="*", metavar="SOURCE")
    parser.add_argument("--all", action="store_true", help="operate on all inventory sources")


def _selected(args: argparse.Namespace, inventory: Inventory) -> list[str]:
    if args.all and args.sources:
        raise ContractError("choose explicit sources or --all, not both")
    if args.all:
        return list(inventory.sources)
    if args.sources:
        for slug in args.sources:
            inventory.require(slug)
        return args.sources
    raise ContractError("provide at least one source or use --all")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mor-l0",
        description="Money on Record source-safety and data-density experiments",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=project_root(),
        help="project root containing config/, data/, docs/, and fixtures/",
    )
    parser.add_argument("--inventory", type=Path, help="override config/sources.yaml")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("inventory", help="show the configured official sources")
    subparsers.add_parser(
        "verify-artifacts", help="rehash every frozen artifact and compare its manifest"
    )
    subparsers.add_parser(
        "validate-versioned",
        help="validate checked-in manifests, profiles, fixtures, and review summaries",
    )
    freeze = subparsers.add_parser("freeze-metadata", help="save immutable Socrata metadata")
    _add_selection(freeze)
    acquire = subparsers.add_parser("acquire", help="save content-addressed source CSVs")
    _add_selection(acquire)
    profile = subparsers.add_parser("profile", help="calculate exact source profiles")
    _add_selection(profile)
    dictionaries = subparsers.add_parser(
        "field-dictionaries", help="render default-deny field dictionaries from metadata"
    )
    _add_selection(dictionaries)
    fixtures = subparsers.add_parser(
        "redact-fixtures", help="make value-free fixtures preserving schema and null shape"
    )
    _add_selection(fixtures)
    fixtures.add_argument("--rows", type=int, default=20)

    privacy = subparsers.add_parser(
        "privacy-check", help="enforce a source allowlist and scan a proposed public CSV"
    )
    privacy.add_argument("path", type=Path)
    privacy.add_argument("--source", required=True)
    privacy.add_argument("--maximum-findings", type=int, default=25)

    candidates = subparsers.add_parser(
        "candidates", help="produce conservative organization candidates for manual review"
    )
    candidates.add_argument("--limit", type=int, default=50)
    review_init = subparsers.add_parser(
        "review-init", help="create a protected, reviewer-editable candidate worksheet"
    )
    review_init.add_argument("--candidates", type=Path)
    review_init.add_argument("--output", type=Path)
    review_validate = subparsers.add_parser(
        "review-validate", help="validate review decisions, evidence, and candidate integrity"
    )
    review_validate.add_argument("--review", type=Path)
    review_validate.add_argument("--candidates", type=Path)
    review_validate.add_argument(
        "--require-complete",
        action="store_true",
        help="fail unless every candidate has a complete review",
    )
    review_summary = subparsers.add_parser(
        "review-summary", help="write a versionable aggregate from a completed review"
    )
    review_summary.add_argument("--review", type=Path)
    review_summary.add_argument("--candidates", type=Path)
    review_summary.add_argument("--output", type=Path)
    subparsers.add_parser(
        "identity-audit", help="write deterministic organization-density and placeholder-code audit"
    )
    return parser


def _count_csv_rows(path: Path) -> int:
    with path.open(encoding="utf-8", newline="") as handle:
        return max(sum(1 for _line in csv.reader(handle)) - 1, 0)


def _project_path(root: Path, value: Path | None, default: str) -> Path:
    path = value or Path(default)
    return path if path.is_absolute() else root / path


def run(args: argparse.Namespace) -> int:
    inventory_path = args.inventory or args.root / "config" / "sources.yaml"
    inventory = load_inventory(inventory_path)

    if args.command == "inventory":
        print("SOURCE\tDATASET\tROLE\tTITLE")
        for source in inventory.sources.values():
            print(f"{source.slug}\t{source.dataset_id}\t{source.role}\t{source.title}")
        return 0

    if args.command == "verify-artifacts":
        count = verify_artifacts(args.root)
        print(f"PASS: {count} metadata/CSV artifacts match their byte counts and SHA-256 hashes")
        return 0

    if args.command == "validate-versioned":
        summary = validate_versioned_data(inventory, root=args.root)
        print(
            "PASS: versioned data is internally consistent "
            f"({summary.manifests} manifests, "
            f"{summary.metadata_artifacts} metadata artifacts, "
            f"{summary.profiles} profiles, {summary.fixtures} redacted fixtures, "
            f"{summary.review_summaries} review summaries)"
        )
        return 0

    if args.command == "privacy-check":
        source = inventory.require(args.source)
        findings = scan_public_csv(
            args.path,
            source,
            maximum_findings=args.maximum_findings,
        )
        if findings:
            print(f"REJECTED: {len(findings)} potential PII finding(s)", file=sys.stderr)
            for finding in findings:
                print(
                    f"row={finding.row_number} field={finding.field} "
                    f"kind={finding.kind} preview={finding.preview}",
                    file=sys.stderr,
                )
            return 1
        print(f"PASS: {args.path} is allowlisted and had no scanner findings")
        return 0

    if args.command == "candidates":
        output = generate_candidates(inventory, limit=args.limit, root=args.root)
        print(f"{output} ({_count_csv_rows(output)} candidates, all require manual review)")
        return 0

    if args.command == "review-init":
        candidates_path = _project_path(
            args.root, args.candidates, "data/derived/l0-organization-candidates.csv"
        )
        output = _project_path(
            args.root,
            args.output,
            "data/derived/l0-organization-candidate-review.csv",
        )
        initialize_review(candidates_path, output)
        print(f"{output} ({_count_csv_rows(output)} candidates awaiting human review)")
        return 0

    if args.command == "review-validate":
        review_path = _project_path(
            args.root,
            args.review,
            "data/derived/l0-organization-candidate-review.csv",
        )
        candidates_path = _project_path(
            args.root, args.candidates, "data/derived/l0-organization-candidates.csv"
        )
        validation = validate_review(
            review_path,
            candidates=candidates_path,
            require_complete=args.require_complete,
        )
        print(
            f"PASS: {validation.reviewed}/{validation.total} candidates reviewed; "
            f"{validation.unreviewed} remain"
        )
        return 0

    if args.command == "review-summary":
        review_path = _project_path(
            args.root,
            args.review,
            "data/derived/l0-organization-candidate-review.csv",
        )
        candidates_path = _project_path(
            args.root, args.candidates, "data/derived/l0-organization-candidates.csv"
        )
        output = _project_path(
            args.root,
            args.output,
            "reports/reviews/l0-organization-candidate-review-summary.json",
        )
        write_review_summary(review_path, candidates_path, output)
        print(f"{output} (aggregate only; safe to review before committing)")
        return 0

    if args.command == "identity-audit":
        outputs = run_identity_audit(inventory, root=args.root)
        for output in outputs:
            print(output)
        return 0

    sources = [inventory.require(slug) for slug in _selected(args, inventory)]
    outputs: list[Path] = []
    for source in sources:
        if args.command == "freeze-metadata":
            print(f"Freezing metadata: {source.slug}", flush=True)
            outputs.append(freeze_metadata(source, args.root))
        elif args.command == "acquire":
            print(f"Acquiring CSV: {source.slug}", flush=True)
            outputs.append(acquire_csv(source, args.root))
        elif args.command == "profile":
            print(f"Profiling: {source.slug}", flush=True)
            outputs.append(profile_csv(source, args.root))
        elif args.command == "field-dictionaries":
            outputs.append(write_field_dictionary(source, args.root))
        elif args.command == "redact-fixtures":
            outputs.append(create_redacted_fixture(source, rows=args.rows, root=args.root))
        else:  # pragma: no cover - argparse constrains commands
            raise AssertionError(args.command)

    if args.command == "profile":
        print(summarize_profiles(outputs))
    else:
        for output in outputs:
            print(output)
    return 0


def main() -> None:
    parser = build_parser()
    try:
        status = run(parser.parse_args())
    except (
        AcquisitionError,
        CandidateError,
        ContractError,
        PublicSchemaError,
        ReviewError,
        VersionedDataError,
        ValueError,
    ) as exc:
        parser.exit(2, f"error: {exc}\n")
    raise SystemExit(status)


if __name__ == "__main__":
    main()
