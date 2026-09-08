"""Local and S3 publication commands; no AWS infrastructure is created here."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .record_browser import ROOT
from .snapshot_store import LocalStore, S3Store, SnapshotError
from .snapshots import publish_snapshot, read_current, restore_snapshot, verify_snapshot


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="mor-snapshot")
    location = result.add_mutually_exclusive_group(required=True)
    location.add_argument("--store", type=Path, help="private local store directory")
    location.add_argument("--s3-bucket", help="existing private bucket for one environment")
    result.add_argument("--aws-account-id", help="required expected S3 bucket owner")
    result.add_argument("--prefix", help="required dedicated environment prefix for S3")
    commands = result.add_subparsers(dest="command", required=True)
    publish = commands.add_parser(
        "publish", help="validate and publish the reviewed browser inputs"
    )
    publish.add_argument("--content", type=Path, default=ROOT / "site/content.json")
    publish.add_argument("--code-revision", required=True, help="full Git SHA of the build code")
    commands.add_parser("current", help="read and verify the current snapshot")
    export = commands.add_parser(
        "export", help="verify and extract a snapshot for the site workflow"
    )
    export.add_argument("--snapshot", required=True)
    export.add_argument("--output", type=Path, required=True, help="new output directory")
    restore = commands.add_parser(
        "restore", help="repoint current to a verified immutable snapshot"
    )
    restore.add_argument("--snapshot", required=True)
    restore.add_argument(
        "--expected-current", required=True, help="snapshot currently being replaced"
    )
    return result


def main() -> None:
    command = parser()
    args = command.parse_args()
    if args.s3_bucket and (not args.aws_account_id or not args.prefix):
        command.error("S3 requires --aws-account-id and --prefix")
    if args.store and (args.aws_account_id or args.prefix):
        command.error("S3 options cannot be used with a local store")
    try:
        store = (
            LocalStore(args.store)
            if args.store
            else S3Store(bucket=args.s3_bucket, account_id=args.aws_account_id, prefix=args.prefix)
        )
        if args.command == "publish":
            snapshot_id = publish_snapshot(
                store, content_path=args.content, code_revision=args.code_revision
            )
        elif args.command == "current":
            current, _ = read_current(store)
            if current is None:
                print(json.dumps({"snapshot_id": None}))
                return
            snapshot_id = current["snapshot_id"]
            verify_snapshot(store, snapshot_id)
        elif args.command == "export":
            snapshot_id = args.snapshot
            verify_snapshot(store, snapshot_id, output=args.output)
        else:
            snapshot_id = args.snapshot
            restore_snapshot(store, snapshot_id, expected_current=args.expected_current)
        print(json.dumps({"snapshot_id": snapshot_id, "status": "ok"}))
    except Exception as error:
        # SDK exceptions and source validation errors can contain source values,
        # signed request URLs or file paths. Never send them to task logs.
        code = error.code if isinstance(error, SnapshotError) else "snapshot_operation_failed"
        command.exit(1, json.dumps({"status": "failed", "code": code}) + "\n")


if __name__ == "__main__":
    main()
