# Hosting architecture research — decision pending

Date: 2026-08-18

This document compares a static S3 and CloudFront application with an
application that also uses Lambda. It is research for issue #1, not an accepted
architecture decision. Prices are public US list prices, generally for US East,
before tax. AWS can change prices and plan eligibility, so the selected plan
must be confirmed in the target accounts during bootstrap.

## Executive result

The first credible Money on Record beta has **zero interactions that require
Lambda**. Pre-rendered organization pages, a small searchable directory,
sorting and filtering a few hundred disclosed rows, downloads, methodology,
source links, and freshness notices can all be generated ahead of time and
served from S3 through CloudFront. Browser JavaScript can provide the local
interactions without turning them into server-side operations.

Lambda would become useful for a real write operation such as a feedback form,
and materially useful for later features such as user accounts, saved searches,
alerts, private review tools, large on-demand exports, or server-side queries
over a dataset too large to ship to the browser. Most of those features also
need authentication, a database or search index, abuse controls, and monitoring;
Lambda by itself is not the feature.

At prototype traffic, the direct price difference is effectively zero. Lambda's
perpetual monthly free tier includes 1 million requests and 400,000 GB-seconds,
and a function with no provisioned concurrency has no idle compute charge.
Avoiding an unused Lambda is therefore primarily a simplicity, security, and
maintenance choice—not meaningful monthly savings.

The strongest starting shape is consequently:

> A static core behind CloudFront, with no placeholder Lambda resources. Keep
> the distribution and Terraform composition able to add an `/api/*` origin
> later when an accepted product feature needs one.

This preserves a low-cost and low-risk first release without closing the door on
serverless work. CloudFront supports multiple origins and path-based cache
behaviors, so adding a dynamic API does not require replacing the static site.
The final selection remains Josh's decision and should be recorded in an ADR
after review.

## What would actually be dynamic?

“Dynamic” should mean that a request depends on the current visitor, performs a
write, needs current server-side state, or queries more data than is safe and
practical to publish to the browser. An animated or interactive page is not
necessarily dynamic in this architectural sense.

| Product behavior | Static files and browser code | What Lambda would add | Beta recommendation |
|---|---|---|---|
| Home, about, methodology, privacy, and source pages | Complete solution | Runtime rendering with no user benefit | Static |
| Organization directory for the initial 31 campaign entities | Publish a compact, privacy-reviewed JSON index; filter locally | Server-side search that is unnecessary at this scale | Static |
| Shareable organization profile URLs and metadata | Pre-render each profile during the build | Runtime SSR, more failure modes, and cold starts | Static |
| Sort/filter/expand profile evidence | Browser code handles the current hundreds of rows easily | Redundant round trips | Static |
| Exact official-source links and freshness timestamps | Embed them in reviewed artifacts | No benefit | Static |
| Reviewed CSV/JSON downloads | Publish precomputed, scanner-passing projections | Useful only for personalized or expensive exports | Static initially |
| Data refresh | Home-server or scheduled build creates a new immutable artifact | Request-time Lambda is the wrong place for the 872 MB raw snapshot | Build-time operation |
| Feedback or contact form | A `mailto:` link is adequate but less polished | One small POST API can validate, rate-limit, and deliver feedback | First plausible Lambda feature |
| Saved searches, bookmarks, or alerts | Cannot persist per-user private state safely | API orchestration, but also needs auth and durable storage | Later product feature |
| Arbitrary search across millions of source rows | Do not publish the raw corpus merely to enable client search | Query API, but also needs a purpose-built access pattern/index and privacy design | Later, only if validated |
| Private identity-review/admin workflow | Static files cannot safely implement privileged writes | Authenticated API plus durable audit state | Later |
| Large or custom exports | Precompute common public exports | Queue and generate uncommon exports on demand | Later if demand exists |

The current exact example—53 campaign-contribution rows and 208 eCheckbook
rows—is comfortably browser-sized. The public beta should not expose the raw
711 MB eCheckbook snapshot or the 872 MB combined raw inputs. Those files remain
private build inputs; only narrow, lineage-preserving, privacy-reviewed outputs
cross the deployment boundary.

## Alternatives

### A. Static application: S3 origin plus CloudFront

The build emits immutable HTML, CSS, JavaScript, and reviewed JSON/CSV assets.
The S3 bucket blocks public access, and CloudFront reads it through Origin Access
Control (OAC). A release switches the distribution to the exact built artifact;
UAT and previews use independently addressable prefixes.

Advantages:

- smallest runtime attack surface and no application server to patch;
- no database, secrets, request handler, or public raw-data endpoint;
- deterministic pages that can be scanned and tested before deployment;
- excellent cacheability, reliable shareable URLs, and straightforward SEO;
- near-zero idle and low-traffic cost;
- the browser still supports search, sort, filters, and expandable evidence.

Limits:

- no safe per-user state or server-side write;
- every data correction needs a rebuild and deployment;
- client-side search stops being appropriate if the reviewed public index grows
  substantially;
- a polished feedback form needs an external service or a later API.

### B. Static core with selected Lambda APIs

The static application remains as above. CloudFront sends a path such as
`/api/*` to API Gateway or another Lambda-capable origin. Only interactions that
need server state cross that boundary.

Advantages:

- preserves static delivery and adds server behavior incrementally;
- no Lambda compute charge while an unprovisioned function is idle;
- a natural fit for small, bursty APIs;
- Python 3.14 is supported in Lambda on Amazon Linux 2023. AWS currently lists
  its managed-runtime deprecation date as June 30, 2029.

Costs and risks:

- every endpoint adds IAM, validation, logs, alerts, abuse protection, retention,
  data-store, and privacy decisions;
- an API can turn a reviewed finite publication into an unbounded data-exposure
  surface;
- accounts, arbitrary search, and alerts require more than a Lambda function;
- a function URL has no endpoint charge but offers fewer API-management controls
  than API Gateway;
- API Gateway adds cost and configuration but supports richer authorization,
  request validation, throttling, and related API features.

CloudFront can use OAC to invoke an IAM-protected Lambda function URL. However,
browser `POST` and `PUT` requests through that arrangement must provide an
`x-amz-content-sha256` body hash. For a normal public feedback POST, an API
Gateway HTTP API is likely the clearer design despite its small per-request
charge. That choice should be made when the endpoint exists, not encoded in an
empty stack now.

### C. Lambda-first rendering and API

Lambda renders most pages or places all public data behind API calls. This is a
valid architecture when content is personalized, authorization is pervasive,
or freshness must be measured in seconds.

None of those conditions exists for the first beta. Lambda-first would make
page availability depend on application execution, give caching and invalidation
more edge cases, require runtime observability immediately, and still need a
data store. It supplies AWS experience but no current user-facing capability.
It is therefore the weakest default unless the beta scope changes materially.

## Current AWS cost tradeoff

### Static delivery choices

CloudFront now offers both conventional pay-as-you-go pricing and flat-rate
plans. The published plan limits and eligibility are not interchangeable:

| CloudFront choice | Published included usage | Likely initial Money on Record cost | Important caveat |
|---|---|---:|---|
| Flat-rate Free | 1 million requests, 100 GB transfer, 5 GB S3 storage credit per month; CDN, TLS, common WAF protections, DDoS protection, DNS, and edge compute bundled | $0/month | No overage charge, but AWS may reduce edge-delivery performance after sustained significant excess. Free has no access/WAF request logs and no custom cache, origin-request, or response-header policies. Account eligibility must be confirmed. |
| Pay as you go within CloudFront Free Tier | 10 million HTTP/HTTPS requests, 1 TB data transfer, and 2 million CloudFront Functions invocations monthly | $0/month at prototype traffic | Usage is aggregated across an AWS Organization; WAF, DNS, storage, and logging are separate services. Beyond the allowance uses metered pricing. |
| Flat-rate Pro | 10 million requests and 50 TB transfer per month, 50 GB S3 storage credit, and logging | $15/month per plan/distribution | Predictable but unnecessary until logs or sustained usage justify it. UAT can remain on a cheaper plan. |

For storage outside a plan credit, S3 Standard's common US-region list price is
$0.023 per GB-month. A 1 GB built site is therefore about $0.023/month and a
5 GB site about $0.115/month before request charges. Money on Record's reviewed
site bundle should initially be much smaller than 1 GB because raw snapshots are
not deployable artifacts. Data transfer from an AWS origin to CloudFront is not
charged. A non-exportable public ACM certificate used with CloudFront has no
certificate charge, and AWS Shield Standard is included at no additional cost.

Using the existing Cloudflare-managed DNS avoids introducing Route 53 merely for
hosted DNS. Exact apex and proxy settings can be decided during the separate DNS
work; they do not change whether page content needs Lambda.

### Lambda request model

The following model intentionally makes the assumptions visible:

- x86 Lambda;
- 512 MB memory;
- 200 ms average billed duration, or 0.1 GB-second per request;
- no provisioned concurrency;
- Lambda list price of $0.0000166667 per GB-second and $0.20 per million
  requests;
- perpetual Lambda free tier of 400,000 GB-seconds and 1 million requests per
  month;
- API Gateway HTTP API estimated at $1.00 per million requests at the first
  published US tier, after any new-account introductory free eligibility;
- no CloudWatch Logs, data-store, transfer, or CloudFront cost included.

| API requests/month | Lambda before free tier | Lambda after monthly free tier | With Lambda function URL | With HTTP API after introductory free eligibility |
|---:|---:|---:|---:|---:|
| 0 | $0.00 | $0.00 | $0.00 | $0.00 |
| 10,000 | $0.02 | $0.00 | $0.00 | about $0.01 |
| 100,000 | $0.19 | $0.00 | $0.00 | about $0.10 |
| 1,000,000 | $1.87 | $0.00 | $0.00 | about $1.00 |
| 5,000,000 | $9.33 | $2.47 | $2.47 | about $7.47 |
| 10,000,000 | $18.67 | $11.80 | $11.80 | about $21.80 |

These numbers demonstrate why low traffic alone does not decide the
architecture. A dormant function and a modestly used lightweight function are
effectively free. Conversely, the actual dynamic feature may incur costs not in
the table: log ingestion and retention, email delivery, DynamoDB reads/writes,
authentication, WAF rules, or a search service.

DynamoDB on-demand can be very inexpensive for known key-value access patterns,
but it is not arbitrary full-text search. Athena is priced per data scanned and
has a 10 MB minimum per query, which makes it useful for analysis rather than
per-keystroke public search. S3 Select is no longer available to new customers.
OpenSearch Serverless has added scale-to-zero behavior, but waking an idle search
collection can take 10–30 seconds and it remains an additional system to secure
and operate. None is justified for a 31-entity browser index.

### Practical beta ceiling

A reasonable target for persistent UAT and production is **$0–$2/month** before
optional paid logging or ancillary services, with an AWS Budget alert at $5 and
a monthly budget at $10. Budget alerts are notifications, not hard spending
caps. The architecture should exclude these sources of idle spend unless a
specific accepted feature requires them:

- provisioned Lambda concurrency;
- NAT Gateway;
- Application Load Balancer;
- RDS;
- an always-on search cluster;
- separately billed WAF rules when a selected CloudFront plan already supplies
  the required baseline protection.

The flat-rate Free plan provides the strongest no-overage guarantee for the
public distribution, while pay as you go has a much larger free request and
transfer allowance. The selected AWS account model matters: plan availability
and organization-wide Free Tier aggregation need to be verified when the UAT
and production accounts are created. AWS currently says accounts in its newer
Free Tier account program cannot subscribe to a flat-rate plan, while older paid
accounts can have up to three Free plans each.

Free and Pro flat-rate plans support five and ten path-based cache behaviors,
respectively, but only AWS-managed default cache, origin-request, and response
header policies. That is sufficient for the proposed static origin. Before
adding an API under the same plan, prove that its required methods, forwarding,
CORS, and security headers fit those managed policies; otherwise use
pay-as-you-go rather than jumping to the $200 Business plan merely to unlock
custom policies. Pricing-plan subscription also needs an infrastructure-as-code
support check during implementation—the current Terraform AWS distribution
resource manages the distribution but does not expose a flat-rate plan argument.

## Operational comparison

| Concern | Static only | Static plus selected Lambda | Lambda-first |
|---|---|---|---|
| Idle application compute | None | None without provisioned concurrency | None without provisioned concurrency |
| Runtime IAM and secrets | CloudFront-to-S3 read path | Adds execution role and possibly service credentials | Required broadly |
| Failure surface | CDN, origin, deployment | Static site remains available when API fails | Page/API behavior can fail together |
| Privacy boundary | Finite artifacts scanned before publish | Each query/write path needs an explicit policy | Broadest request-time boundary |
| Observability needs | Deployment and CDN signals | Per-endpoint errors, latency, abuse, and logs | Required for the whole application |
| Data freshness | Rebuild and deploy | Rebuild for published evidence; API state can be current | Can be current, subject to upstream refresh |
| Career-relevant AWS work | Terraform, S3, CloudFront, OAC, ACM, IAM/OIDC, environments, releases | Adds Lambda, API Gateway, logs, tracing, data services | Adds them immediately, whether useful or not |
| Ease of adding later behavior | Add `/api/*` origin | Add endpoints/services as features justify them | Already available |

Static-first is not “avoiding AWS.” It still exercises production-grade account
separation, GitHub OIDC, IAM, Terraform state, S3 security, CloudFront behavior,
TLS, deployment promotion, budgets, monitoring, artifact provenance, UAT, and
release automation. Lambda becomes more valuable career evidence when it solves
a real product problem and can be tested as such.

## Recommended boundary and upgrade triggers

If the static-core option is selected, the first thin slice should produce one
immutable bundle containing:

- pre-rendered HTML routes;
- versioned CSS and browser JavaScript;
- a compact organization search index;
- privacy-reviewed per-profile data projections and optional downloads;
- source-lineage URLs, build/release identity, and freshness metadata;
- no raw source snapshots, secrets, private review notes, or ambiguous internal
  identity material.

Add Lambda only when an accepted story meets at least one trigger:

1. A user must create or change durable state.
2. The response must depend on authenticated identity or private authorization.
3. The reviewed public query corpus no longer fits a practical browser artifact.
4. A requested export is too expensive to precompute for everyone.
5. A time-sensitive response cannot tolerate the build-and-release freshness
   window.

Before implementing that story, document its data store, authorization,
retention, abuse limit, logs, failure behavior, and cost alarm. The API should
return narrow public projections rather than exposing raw source-shaped query
power.

## Decision to record after review

Josh can make three separable choices from this research:

1. **Runtime shape:** static core with no initial API; static core plus one real
   initial API such as feedback; or Lambda-first rendering/API.
2. **CloudFront billing:** flat-rate Free for the no-overage ceiling, or
   pay-as-you-go for its larger Free Tier allowance and full configuration
   control.
3. **Access logging at launch:** accept the Free plan's lack of plan logging, use
   separately priced capabilities where compatible, or select Pro at $15/month
   for its included logging and larger allowance.

The resulting ADR should explicitly state that the choice can be revisited by
feature trigger; it need not forecast the final architecture of a successful
larger product.

## Official sources

- [Amazon CloudFront pricing](https://aws.amazon.com/cloudfront/pricing/)
- [Amazon CloudFront FAQ](https://aws.amazon.com/cloudfront/faqs/)
- [CloudFront flat-rate pricing plans](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/flat-rate-pricing-plan.html)
- [CloudFront cache behavior settings](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/DownloadDistValuesCacheBehavior.html)
- [Terraform AWS provider: CloudFront distribution resource](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/cloudfront_distribution)
- [Restrict access to a Lambda function URL origin with OAC](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/private-content-restricting-access-to-lambda.html)
- [AWS Lambda pricing](https://aws.amazon.com/lambda/pricing/)
- [Choosing between Lambda function URLs and API Gateway](https://docs.aws.amazon.com/lambda/latest/dg/furls-http-invoke-decision.html)
- [Amazon API Gateway pricing](https://aws.amazon.com/api-gateway/pricing/)
- [Lambda runtimes for Python](https://docs.aws.amazon.com/lambda/latest/dg/lambda-python.html)
- [Lambda quotas](https://docs.aws.amazon.com/lambda/latest/dg/gettingstarted-limits.html)
- [Amazon S3 pricing](https://aws.amazon.com/s3/pricing/)
- [Amazon S3 Select availability](https://docs.aws.amazon.com/AmazonS3/latest/userguide/selecting-content-from-objects.html)
- [Amazon DynamoDB pricing](https://aws.amazon.com/dynamodb/pricing/)
- [Amazon Athena pricing](https://aws.amazon.com/athena/pricing/)
- [Scale OpenSearch Serverless collections to zero](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/serverless-scale-to-zero.html)
- [AWS Certificate Manager pricing](https://aws.amazon.com/certificate-manager/pricing/)
- [AWS Shield Standard](https://docs.aws.amazon.com/shield/)
