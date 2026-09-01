mock_provider "aws" {
  override_during = plan

  mock_data "aws_cloudfront_cache_policy" {
    defaults = {
      id = "managed-cache-policy-id"
    }
  }

  mock_resource "aws_cloudfront_response_headers_policy" {
    defaults = {
      id = "site-response-headers-policy-id"
    }
  }

  mock_resource "aws_s3_bucket" {
    defaults = {
      arn                         = "arn:aws:s3:::money-on-record-uat-123456789012-site"
      bucket                      = "money-on-record-uat-123456789012-site"
      bucket_regional_domain_name = "money-on-record-uat-123456789012-site.s3.us-east-1.amazonaws.com"
      id                          = "money-on-record-uat-123456789012-site"
    }
  }

  mock_resource "aws_cloudfront_distribution" {
    defaults = {
      arn         = "arn:aws:cloudfront::123456789012:distribution/E123EXAMPLE"
      domain_name = "d123example.cloudfront.net"
      id          = "E123EXAMPLE"
    }
  }
}

run "private_static_site" {
  command = plan

  variables {
    bucket_name = "money-on-record-uat-123456789012-site"
    environment = "uat"
  }

  assert {
    condition = (
      module.cdn.cloudfront_response_headers_policies[local.response_headers_policy_key].id ==
      "site-response-headers-policy-id"
    )
    error_message = "The module must create the project-owned response header policy."
  }

  assert {
    condition     = output.bucket_name == "money-on-record-uat-123456789012-site"
    error_message = "The module must expose the exact private artifact bucket."
  }

  assert {
    condition     = output.site_url == "https://d123example.cloudfront.net"
    error_message = "The default site URL must use the generated HTTPS CloudFront hostname."
  }

  assert {
    condition = (
      jsondecode(aws_s3_bucket_policy.site.policy).Statement[0].Principal.Service ==
      "cloudfront.amazonaws.com"
    )
    error_message = "The bucket policy must grant read access only through CloudFront."
  }

  assert {
    condition = (
      jsondecode(aws_s3_bucket_policy.site.policy).Statement[0].Condition.StringEquals["AWS:SourceArn"] ==
      "arn:aws:cloudfront::123456789012:distribution/E123EXAMPLE"
    )
    error_message = "The bucket policy must scope CloudFront access to this distribution."
  }

  assert {
    condition = (
      jsondecode(aws_s3_bucket_policy.site.policy).Statement[1].Condition.Bool["aws:SecureTransport"] ==
      "false"
    )
    error_message = "The bucket policy must deny insecure transport."
  }

  assert {
    condition = strcontains(
      module.cdn.cloudfront_response_headers_policies[local.response_headers_policy_key].security_headers_config[0].content_security_policy[0].content_security_policy,
      "frame-ancestors 'none'",
    )
    error_message = "The response policy must prevent the site from being framed."
  }

  assert {
    condition = one([
      for item in module.cdn.cloudfront_response_headers_policies[local.response_headers_policy_key].custom_headers_config[0].items :
      item.value if item.header == "Permissions-Policy"
    ]) == local.permissions_policy
    error_message = "The response policy must disable unused browser capabilities."
  }

  assert {
    condition = toset([
      for response in local.custom_error_responses :
      response.error_code
    ]) == toset([403, 404])
    error_message = "Missing private-origin objects must use the browser-visible 404 page."
  }
}

run "reject_alias_without_certificate" {
  command = plan

  variables {
    bucket_name    = "money-on-record-production-123456789012-site"
    environment    = "production"
    domain_aliases = ["moneyonrecord.org"]
  }

  expect_failures = [var.domain_aliases]
}

run "custom_domain" {
  command = plan

  variables {
    bucket_name         = "money-on-record-production-123456789012-site"
    environment         = "production"
    domain_aliases      = ["moneyonrecord.org"]
    acm_certificate_arn = "arn:aws:acm:us-east-1:123456789012:certificate/example"
  }

  assert {
    condition     = output.site_url == "https://moneyonrecord.org"
    error_message = "The site URL must prefer the configured custom domain."
  }
}
