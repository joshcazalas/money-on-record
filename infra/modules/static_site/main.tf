locals {
  origin_id                   = "site-artifacts"
  response_headers_policy_key = "site-security"
  custom_error_responses = [
    {
      error_caching_min_ttl = 0
      error_code            = 403
      response_code         = 404
      response_page_path    = "/404.html"
    },
    {
      error_caching_min_ttl = 0
      error_code            = 404
      response_code         = 404
      response_page_path    = "/404.html"
    },
  ]
  content_security_policy = join("; ", [
    "default-src 'none'",
    "style-src 'self'",
    "base-uri 'none'",
    "form-action 'none'",
    "frame-ancestors 'none'",
  ])
  permissions_policy = join(", ", [
    "accelerometer=()",
    "autoplay=()",
    "camera=()",
    "geolocation=()",
    "gyroscope=()",
    "magnetometer=()",
    "microphone=()",
    "payment=()",
    "usb=()",
  ])
  tags = merge(var.tags, {
    Component   = "static-site"
    Environment = var.environment
  })
}

data "aws_cloudfront_cache_policy" "caching_optimized" {
  name = "Managed-CachingOptimized"
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

  custom_error_response = local.custom_error_responses

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
    target_origin_id            = local.origin_id
    viewer_protocol_policy      = "redirect-to-https"
    allowed_methods             = ["GET", "HEAD", "OPTIONS"]
    cached_methods              = ["GET", "HEAD"]
    cache_policy_id             = data.aws_cloudfront_cache_policy.caching_optimized.id
    response_headers_policy_key = local.response_headers_policy_key
    compress                    = true
  }

  response_headers_policies = {
    (local.response_headers_policy_key) = {
      name    = "money-on-record-${var.environment}-security-v1"
      comment = "Security and privacy headers for the Money on Record ${var.environment} site"
      custom_headers_config = {
        items = [
          {
            header   = "Permissions-Policy"
            override = true
            value    = local.permissions_policy
          },
          {
            header   = "X-Robots-Tag"
            override = true
            value    = "noindex, nofollow, noarchive"
          },
        ]
      }
      security_headers_config = {
        content_security_policy = {
          content_security_policy = local.content_security_policy
          override                = true
        }
        content_type_options = {
          override = true
        }
        frame_options = {
          frame_option = "DENY"
          override     = true
        }
        referrer_policy = {
          referrer_policy = "no-referrer"
          override        = true
        }
        strict_transport_security = {
          access_control_max_age_sec = 31536000
          include_subdomains         = true
          override                   = true
          preload                    = true
        }
        xss_protection = {
          mode_block = true
          override   = true
          protection = true
        }
      }
    }
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
