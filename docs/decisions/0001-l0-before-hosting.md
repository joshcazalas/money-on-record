# 0001 — Prove source safety before choosing hosting

Status: accepted for the completed local evidence phase; sequencing amended by
[`0002`](0002-deploy-beta-before-external-validation.md)

Money on Record did not create Cloudflare or AWS infrastructure during the
initial local evidence phase. Source integrity, privacy, and
organization-profile density could be evaluated locally. ADR 0002 corrects the
original assumption that audience usefulness could be evaluated credibly
without first deploying a real product.

The leading post-L0 shape is static-first S3 plus CloudFront, with reviewed
precomputed data artifacts. Lambda remains an option for genuinely dynamic
features, not bulk source ingestion. Complete eCheckbook snapshots are hundreds
of megabytes and fit the existing always-on home server or a scheduled container
far better than a Lambda execution.

This was a sequencing decision, not a permanent rejection of Lambda,
home-server hosting, or another platform. The local source-safety and density
work is now complete enough to begin the deployed beta. External usability no
longer blocks that implementation; ADR 0002 records why validation follows a
credible browser-accessible product.
