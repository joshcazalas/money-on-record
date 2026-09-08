# Snapshot publication

`mor-snapshot` packages the reviewed browser inputs into immutable snapshots.
It runs locally or against an existing private S3 bucket using the same
publication and recovery code. It does not yet acquire fresh data or run on a
schedule. Those stages are tracked in [#30](https://github.com/joshcazalas/money-on-record/issues/30)
and [#28](https://github.com/joshcazalas/money-on-record/issues/28).

## Local use

Run from the repository checkout. The publisher currently uses its checked-in
source registry, acquisition receipts, metadata, profiles, and frontend files.
The full Git revision records the code used to produce the snapshot; use a clean,
committed checkout for reproducible publication.

```bash
uv run --locked mor-snapshot --store build/etl-store publish \
  --code-revision "$(git rev-parse HEAD)"
uv run --locked mor-snapshot --store build/etl-store current
```

The publication command prints the snapshot ID. Use it to extract a verified
site artifact into a new directory or restore an earlier snapshot:

```bash
uv run --locked mor-snapshot --store build/etl-store export \
  --snapshot '<snapshot-id>' --output build/restored-site
uv run --locked mor-snapshot --store build/etl-store restore \
  --snapshot '<earlier-snapshot-id>' --expected-current '<current-snapshot-id>'
```

Exported files have the same `site-manifest.json` contract as `build-site` and
can be consumed by the static-site publishing workflow. Current UAT/production
workflows still build from reviewed repository inputs; they do not consume this
store yet. Restoring this pointer alone does not redeploy CloudFront.

## Storage contract

Each store belongs to one environment. Operational data belongs in private S3;
small reviewed public selections and representative manifests may remain in Git.
Never point the local frontend server or a public CloudFront origin at a store.
Local stores should live under ignored `build/`; created object files are mode
0600 and directories are mode 0700. Local concurrency uses POSIX file locks and
atomic rename on one host; it is not a distributed filesystem lock.

| Key | Contents | Write behavior |
| --- | --- | --- |
| `site/<sha256>` | Deterministic, validated site ZIP | Create only |
| `snapshots/<UTC-acquisition-time>-<manifest-sha256>.json` | File hashes, source lineage, archive reference, transform and code version | Create only |
| `current.json` | Selected snapshot, publication time, unique generation | Conditional replacement |
| `runs/<UTC-run-time>-<random-id>/failure.json` | Failure code and stage, no exception text or source values | Create only |
| `raw/`, `metadata/`, `normalized/`, `candidates/`, `resolved/` | Reserved content-addressed stage objects, via `put_blob` | Create only |

The current publisher retains the browser archive and its manifest. It records
source raw/metadata hashes, sizes, retrieval times, schema fingerprints, source
update times, and row counts from the existing acquisition evidence. It does
**not** copy the original large raw extracts into the store: manifests explicitly
say `raw_storage: external-lineage-only`. Upstream acquisition must persist those
objects before scheduled runs are enabled. This bootstrap mode is not a claim
that a complete raw snapshot has been archived.

Keep manifests and published archives indefinitely until a reviewed retention
policy exists. There is no automatic deletion or cleanup command. Large raw
extract retention can be decided separately without discarding lineage.

## Publication and recovery guarantees

The publisher reads the current generation before doing work. It enforces the
existing browser field, coverage, checksum, privacy, date, amount, and identifier
gates; checks the versioned acquisition evidence; builds twice for deterministic
output; stores the archive and manifest; then reads them back and verifies their
hashes and lineage before changing `current`.

Identical source inputs and code revision produce the same snapshot ID in any
store. The timestamp comes from acquisition receipts, not publication time.
Replaying the current snapshot is a no-op. Conflicting content at an immutable
key is an error. The source freshness, schema drift, row/amount anomaly, retry,
and completeness gates for fresh acquisitions remain part of the next pipeline
stage; the publication command does not claim to implement them.

S3 writes use `If-None-Match: *` for immutable objects and the observed ETag with
`If-Match` for an existing pointer. A unique generation also prevents a stale
writer from succeeding after an A → B → A rollback. A concurrency conflict fails
the run; it never silently rereads and overwrites a newer publication. S3
conditional write behavior is documented by [AWS](https://docs.aws.amazon.com/AmazonS3/latest/userguide/conditional-writes.html).

Failures before pointer replacement leave the previous pointer unchanged. A
lost response during replacement has an ambiguous outcome: the failure report
says `indeterminate`, and operators should run `current` to inspect the result.
Either observable pointer refers to a complete verified snapshot. Failure
reports are best effort when storage itself is unavailable. The CLI exits
nonzero with a fixed error code and suppresses SDK/source exception contents.
An OS kill may leave no failure report; ECS task failure alerts remain necessary.

Restore verifies the original immutable manifest and archive, checks the
operator's expected current snapshot, then conditionally replaces the pointer.
It does not reacquire sources or rebuild the site. Export verifies the whole
archive before extracting files into a new directory.

## S3 runtime interface

Install the optional official AWS SDK with `uv sync --locked --extra s3`. Supply
all three location arguments explicitly:

```bash
uv run --locked --extra s3 mor-snapshot \
  --s3-bucket '<private-environment-data-bucket>' \
  --aws-account-id '<12-digit-bucket-owner>' --prefix '<environment-prefix>' \
  current
```

The same location arguments work with `publish`, `export`, and `restore`.
Every S3 request supplies the expected bucket owner. Use normal SDK credentials
locally and the ECS task role on Fargate. No keys, personal contact information,
or private registry credentials belong in these arguments or manifests.

Provision a dedicated environment data bucket with public access blocked,
versioning, encryption, and TLS required. The runtime needs `s3:GetObject` and
`s3:PutObject` on its exact store prefix; no bucket listing, object deletion,
ACL, IAM, or cross-environment permissions are needed. Enforce conditional writes
in the bucket policy as defense in depth. The adapter uses service-validated
SHA-256 checksums, SSE-S3, bounded network retries/timeouts, streaming single-part
uploads up to 5 GiB, and bounded reads for public artifacts. Multipart ingestion
is deferred until a source requires it. The S3 adapter is tested with the real
SDK's request/response models; live bucket and Fargate validation remain required.
