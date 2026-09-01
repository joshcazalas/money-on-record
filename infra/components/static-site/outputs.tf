output "artifact_bucket_name" {
  description = "Private bucket receiving immutable application artifacts."
  value       = module.static_site.bucket_name
}

output "cloudfront_distribution_id" {
  description = "Distribution ID used by the deploy workflow."
  value       = module.static_site.cloudfront_distribution_id
}

output "configured_site_bucket_name" {
  description = "Workspace-bound S3 bucket name before resource creation."
  value       = local.site_bucket_name
}

output "environment" {
  description = "Selected deployment environment."
  value       = local.environment
}

output "site_url" {
  description = "Environment site URL."
  value       = module.static_site.site_url
}

output "site_object_keys" {
  description = "Rendered browser object keys managed by the selected environment."
  value       = module.static_site.site_object_keys
}

output "state_object_key" {
  description = "Centralized S3 backend object key for this environment."
  value       = local.state_object_key
}

output "workload_account_id" {
  description = "AWS workload account selected by the environment."
  value       = local.aws_account_id
}
