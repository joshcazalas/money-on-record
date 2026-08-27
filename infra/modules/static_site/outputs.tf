output "bucket_name" {
  description = "Private S3 artifact bucket name."
  value       = module.site_bucket.s3_bucket_id
}

output "bucket_arn" {
  description = "Private S3 artifact bucket ARN."
  value       = module.site_bucket.s3_bucket_arn
}

output "cloudfront_distribution_id" {
  description = "CloudFront distribution ID used for deployments and invalidations."
  value       = module.cdn.cloudfront_distribution_id
}

output "cloudfront_distribution_arn" {
  description = "CloudFront distribution ARN."
  value       = module.cdn.cloudfront_distribution_arn
}

output "cloudfront_domain_name" {
  description = "Generated CloudFront hostname."
  value       = module.cdn.cloudfront_distribution_domain_name
}

output "site_url" {
  description = "HTTPS URL using the first alias or generated CloudFront hostname."
  value = format(
    "https://%s",
    length(var.domain_aliases) == 0 ? module.cdn.cloudfront_distribution_domain_name : var.domain_aliases[0],
  )
}
