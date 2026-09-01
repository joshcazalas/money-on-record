from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def _workflow(name: str) -> str:
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def test_terraform_owns_every_rendered_site_object_and_its_cache_metadata() -> None:
    source = (ROOT / "infra/modules/static_site/main.tf").read_text(encoding="utf-8")
    component = (ROOT / "infra/components/static-site/main.tf").read_text(encoding="utf-8")

    assert 'resource "aws_s3_object" "site"' in source
    assert "for_each = local.site_artifact_files" in source
    assert "source_hash            = filesha256(" in source
    assert "etag                   = filemd5(" in source
    assert '"public, max-age=31536000, immutable"' in source
    assert '"no-cache, max-age=0, must-revalidate"' in source
    assert '"text/html; charset=utf-8"' in source
    assert '"text/css; charset=utf-8"' in source
    assert "site_artifact_directory = var.site_artifact_directory" in component
    assert "aws cloudfront create-invalidation" not in source


def test_uat_deploy_builds_before_aws_and_terraform_apply_is_the_deployment() -> None:
    source = _workflow("reusable-terraform-deploy.yml")
    prepare = source.index("Prepare site artifact")
    assume = source.index("Assume environment deployment role")
    plan = source.index("Plan deployment")
    apply = source.index("Apply deployment")

    assert prepare < assume < plan < apply
    assert "TF_VAR_site_artifact_directory: ../../../build/site" in source
    assert 'if [[ "$TF_WORKSPACE" == "production" ]]' in source
    assert "uv run --locked mor-l0 build-site" in source
    assert "terraform apply" in source
    assert "continue-on-error" not in source
    assert "terraform show -json" not in source
    assert "Smoke-test" not in source
    assert "aws s3 sync" not in source
    assert "create-invalidation" not in source
    assert "reusable-site-publish" not in source


def test_production_deploy_uses_the_exact_immutable_release_site_asset() -> None:
    source = _workflow("reusable-terraform-deploy.yml")

    assert 'release_version="${RELEASE_TAG#v}"' in source
    assert 'gh release download "$RELEASE_TAG"' in source
    assert '--pattern "money-on-record-site-${release_version}.zip"' in source
    assert '--pattern "money-on-record-site-${release_version}.zip.sha256"' in source
    assert '--pattern "provenance.sigstore.json"' in source
    assert 'gh attestation verify "$archive"' in source
    assert '--bundle "$release_directory/provenance.sigstore.json"' in source
    assert "mor-l0 verify-site" in source
    assert "--output build/site" in source
    assert source.index('gh release download "$RELEASE_TAG"') < source.index(
        "Assume environment deployment role"
    )


def test_pr_plan_build_is_unprivileged_then_verified_before_aws() -> None:
    source = _workflow("reusable-terraform-plan.yml")
    build_job, plan_job = source.split("\n  plan:\n", maxsplit=1)

    assert "build-site:" in build_job
    assert "id-token: write" not in build_job.split("\n  build-site:\n", maxsplit=1)[1]
    assert "mor-l0 build-site" in build_job
    assert "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a" in build_job
    assert "actions: read" in plan_job
    assert "Download proposed site" in plan_job
    assert "Verify proposed site with trusted code" in plan_job
    assert "TF_VAR_site_artifact_directory: ../../../build/site" in plan_job
    assert plan_job.index("Verify proposed site with trusted code") < plan_job.index(
        "Assume environment plan role"
    )


def test_ci_and_releases_build_the_deterministic_site_artifact() -> None:
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
    source = (ROOT / "infra/modules/static_site/main.tf").read_text(encoding="utf-8")

    assert 'response_headers_policy_key = "site-security"' in source
    assert "\"default-src 'none'\"" in source
    assert "\"frame-ancestors 'none'\"" in source
    assert 'header   = "Permissions-Policy"' in source
    assert 'header   = "X-Robots-Tag"' in source
    assert 'referrer_policy = "no-referrer"' in source
    assert 'response_page_path    = "/404.html"' in source
    assert source.count("response_code         = 404") == 2


def test_no_parallel_site_publisher_workflow_remains() -> None:
    assert not (WORKFLOWS / "site-publish-uat.yml").exists()
    assert not (WORKFLOWS / "reusable-site-publish.yml").exists()
