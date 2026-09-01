output "artifact_bucket_name" {
  description = "Private bucket receiving immutable application artifacts."
  value       = local.workspace_supported ? module.static_site[0].bucket_name : null
}

output "cloudfront_distribution_id" {
  description = "Distribution ID used by the deploy workflow."
  value       = local.workspace_supported ? module.static_site[0].cloudfront_distribution_id : null
}

output "configured_site_bucket_name" {
  description = "Workspace-bound S3 bucket name before resource creation."
  value       = local.site_bucket_name
}

output "environment" {
  description = "Canonical environment selected by the current workspace."
  value       = local.environment
}

output "site_url" {
  description = "Workspace site URL."
  value       = local.workspace_supported ? module.static_site[0].site_url : null
}

output "site_object_keys" {
  description = "Rendered browser object keys managed by the selected environment."
  value       = local.workspace_supported ? module.static_site[0].site_object_keys : []
}

output "state_object_key" {
  description = "Derived centralized S3 backend object key for this workspace."
  value       = local.state_object_key
}

output "workload_account_id" {
  description = "AWS workload account selected by the current workspace."
  value       = local.aws_account_id
}
