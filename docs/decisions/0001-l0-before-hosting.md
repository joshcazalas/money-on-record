# 0001 — Prove source safety before choosing hosting

Status: accepted for L0

Money on Record will not create Cloudflare or AWS infrastructure during L0.
Source integrity, privacy, organization-profile density, and user usefulness can
all be evaluated locally, and those results determine what the deployed product
actually needs.

The leading post-L0 shape is static-first S3 plus CloudFront, with reviewed
precomputed data artifacts. Lambda remains an option for genuinely dynamic
features, not bulk source ingestion. Complete eCheckbook snapshots are hundreds
of megabytes and fit the existing always-on home server or a scheduled container
far better than a Lambda execution.

This is a sequencing decision, not a permanent rejection of Lambda, home-server
hosting, or another platform. Revisit it after the static profile test defines
the required interactions and after actual traffic justifies recurring spend.
