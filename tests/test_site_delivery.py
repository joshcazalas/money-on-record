from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def _workflow(name: str) -> str:
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def test_uat_site_publish_is_manual_default_off_and_builds_without_aws() -> None:
    source = _workflow("site-publish-uat.yml")
    build_job, publish_job = source.split("\n  publish:\n", maxsplit=1)

    assert "workflow_dispatch:" in source
    assert "confirm_uat_publication:" in source
    assert "default: false" in source
    assert "if: inputs.confirm_uat_publication" in build_job
    assert "push:" not in source
    assert "pull_request:" not in source
    assert "schedule:" not in source
    assert "permissions: {}" in source
    assert "id-token: write" not in build_job
    assert "pytest tests/test_site.py" in build_job
    assert "mor-l0 build-site" in build_job
    assert "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a" in build_job
    assert "compression-level: 0" in build_job
    assert "retention-days: 1" in build_job
    assert "id-token: write" in publish_job
    assert (
        "uses: joshcazalas/money-on-record/.github/workflows/reusable-site-publish.yml@main"
        in publish_job
    )
    assert "artifact_digest: ${{ needs.build.outputs.artifact_digest }}" in publish_job
    assert "revision: ${{ github.sha }}" in publish_job


def test_trusted_site_publisher_binds_caller_revision_artifact_and_uat() -> None:
    source = _workflow("reusable-site-publish.yml")

    for expected in (
        "CALLER_EVENT",
        "CALLER_ACTOR_ID",
        "CALLER_OWNER_ID",
        "CALLER_REPOSITORY_ID",
        "CALLER_REF",
        "EXPECTED_ACTOR_ID: '73436834'",
        "EXPECTED_REPOSITORY_ID: '1338755168'",
        '[[ "$CALLER_EVENT" == "workflow_dispatch" ]]',
        '[[ "$CALLER_REF" == "refs/heads/main" ]]',
        '[[ "$PUBLISH_REVISION" == "$CALLER_SHA" ]]',
        "git/ref/heads/main",
        "Only the current main revision may be published to UAT",
        "environment: uat",
        "EXPECTED_DEPLOYMENT_ACCOUNT_ID: '245459924498'",
        "EXPECTED_WORKLOAD_ACCOUNT_ID: '732006412638'",
        "EXPECTED_SITE_BUCKET: money-on-record-uat-732006412638-site",
        "EXPECTED_SITE_DISTRIBUTION_ID: EEZ2CUTI93E10",
        "role/MoneyOnRecordArtifactPublishUat",
        "role/MoneyOnRecordArtifactPublish",
    ):
        assert expected in source

    assert "cancel-in-progress: false" in source
    assert "environment: production" not in source
    assert "terraform apply" not in source
    assert "pull_request:" not in source
    assert "push:" not in source


def test_trusted_site_publisher_verifies_before_aws_and_proves_isolation() -> None:
    source = _workflow("reusable-site-publish.yml")
    download = source.index("Download run-local site artifact")
    verify = source.index("Verify and extract the authorized artifact")
    assume = source.index("Assume UAT artifact publishing hub role")

    assert download < verify < assume
    assert "money-on-record-site.zip money-on-record-site.zip.sha256" in source
    assert '--expected-sha256 "$ARTIFACT_DIGEST"' in source
    assert source.count("configure-aws-credentials@e6de054238d6b7531b4efff3b6587d9aade6a06c") == 2
    assert "allowed-account-ids: ${{ env.EXPECTED_DEPLOYMENT_ACCOUNT_ID }}" in source
    assert "allowed-account-ids: ${{ env.EXPECTED_WORKLOAD_ACCOUNT_ID }}" in source
    assert "role-chaining: true" in source
    assert "FORBIDDEN_STATE_BUCKET" in source
    assert "FORBIDDEN_STATE_KEY" in source
    assert "FORBIDDEN_WORKLOAD_ROLE_ARN" in source
    assert "The artifact role unexpectedly read Terraform state" in source
    assert "The UAT artifact role unexpectedly accessed the production site bucket" in source


def test_uat_publish_uses_scoped_cache_deletion_invalidation_and_smoke_tests() -> None:
    source = _workflow("reusable-site-publish.yml")

    assert source.count('"s3://${SITE_BUCKET}') == 2
    assert source.count("--delete") == 2
    assert "--exclude 'assets/*'" in source
    assert "no-cache, max-age=0, must-revalidate" in source
    assert "public, max-age=31536000, immutable" in source
    assert '--distribution-id "$SITE_DISTRIBUTION_ID"' in source
    assert "--paths '/*'" not in source
    for path in (
        "'/'",
        "'/index.html'",
        "'/404.html'",
        "'/robots.txt'",
        "'/site-manifest.json'",
        "'/profiles/*'",
    ):
        assert path in source
    assert "aws cloudfront wait invalidation-completed" in source
    assert "content-security-policy:" in source
    assert "permissions-policy:" in source
    assert "referrer-policy: no-referrer" in source
    assert "x-content-type-options: nosniff" in source
    assert "x-robots-tag: noindex, nofollow, noarchive" in source
    assert "/profiles/austin-board-of-realtors/index.html" in source
    assert "data.austintexas.gov/resource/3kfv-biw6.json" in source
    assert "There is no profile at this address" in source
    assert "Verified UAT site publication" in source


def test_ci_and_releases_build_the_same_static_site_artifact() -> None:
    ci = _workflow("ci.yml")
    release = _workflow("release.yml")

    assert "site-artifact:" in ci
    assert "mor-l0 build-site" in ci
    assert "mor-l0 verify-site" in ci
    assert "money-on-record-site.zip.sha256" in ci
    assert "mor-l0 build-site" in release
    assert "money-on-record-site-${RELEASE_VERSION}.zip" in release
    assert "money-on-record-site-${RELEASE_VERSION}.zip.sha256" in release
    assert "subject-path: release/assets/*" in release


def test_cloudfront_serves_security_headers_and_a_browser_404() -> None:
    source = (ROOT / "infra" / "modules" / "static_site" / "main.tf").read_text(encoding="utf-8")

    assert 'response_headers_policy_key = "site-security"' in source
    assert "\"default-src 'none'\"" in source
    assert "\"frame-ancestors 'none'\"" in source
    assert 'header   = "Permissions-Policy"' in source
    assert 'header   = "X-Robots-Tag"' in source
    assert 'referrer_policy = "no-referrer"' in source
    assert 'response_page_path    = "/404.html"' in source
    assert source.count("response_code         = 404") == 2
