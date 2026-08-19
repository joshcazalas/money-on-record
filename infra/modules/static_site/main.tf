locals {
  origin_id = "site-artifacts"
  tags = merge(var.tags, {
    Component   = "static-site"
    Environment = var.environment
  })
}

data "aws_cloudfront_cache_policy" "caching_optimized" {
  name = "Managed-CachingOptimized"
}

data "aws_cloudfront_response_headers_policy" "security_headers" {
  name = "Managed-SecurityHeadersPolicy"
}

module "site_bucket" {
  source  = "terraform-aws-modules/s3-bucket/aws"
  version = "5.15.4"

  bucket = var.bucket_name

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true

  control_object_ownership = true
  object_ownership         = "BucketOwnerEnforced"
  force_destroy            = false

  server_side_encryption_configuration = {
    rule = {
      apply_server_side_encryption_by_default = {
        sse_algorithm = "AES256"
      }
    }
  }

  versioning = {
    enabled = true
  }

  tags = local.tags
}

module "cdn" {
  source  = "terraform-aws-modules/cloudfront/aws"
  version = "6.7.0"

  aliases             = length(var.domain_aliases) == 0 ? null : var.domain_aliases
  comment             = "Money on Record ${var.environment} static site"
  default_root_object = "index.html"
  enabled             = true
  http_version        = "http2and3"
  is_ipv6_enabled     = true
  web_acl_id          = var.web_acl_id

  create_monitoring_subscription       = false
  realtime_metrics_subscription_status = "Disabled"

  origin_access_control = {
    site = {
      description      = "CloudFront access to the private ${var.environment} site bucket"
      origin_type      = "s3"
      signing_behavior = "always"
      signing_protocol = "sigv4"
    }
  }

  origin = {
    site = {
      domain_name               = module.site_bucket.s3_bucket_bucket_regional_domain_name
      origin_access_control_key = "site"
      origin_id                 = local.origin_id
    }
  }

  default_cache_behavior = {
    target_origin_id           = local.origin_id
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = ["GET", "HEAD", "OPTIONS"]
    cached_methods             = ["GET", "HEAD"]
    cache_policy_id            = data.aws_cloudfront_cache_policy.caching_optimized.id
    response_headers_policy_id = data.aws_cloudfront_response_headers_policy.security_headers.id
    compress                   = true
  }

  viewer_certificate = {
    acm_certificate_arn            = var.acm_certificate_arn
    cloudfront_default_certificate = var.acm_certificate_arn == null ? true : null
    minimum_protocol_version       = var.acm_certificate_arn == null ? "TLSv1" : "TLSv1.2_2025"
    ssl_support_method             = var.acm_certificate_arn == null ? null : "sni-only"
  }

  tags = local.tags
}

resource "aws_s3_bucket_policy" "site" {
  bucket = module.site_bucket.s3_bucket_id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowCloudFrontRead"
        Effect = "Allow"
        Principal = {
          Service = "cloudfront.amazonaws.com"
        }
        Action   = "s3:GetObject"
        Resource = "${module.site_bucket.s3_bucket_arn}/*"
        Condition = {
          StringEquals = {
            "AWS:SourceArn" = module.cdn.cloudfront_distribution_arn
          }
        }
      },
      {
        Sid       = "DenyInsecureTransport"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource = [
          module.site_bucket.s3_bucket_arn,
          "${module.site_bucket.s3_bucket_arn}/*",
        ]
        Condition = {
          Bool = {
            "aws:SecureTransport" = "false"
          }
        }
      },
    ]
  })
}
