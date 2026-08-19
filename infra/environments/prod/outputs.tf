output "artifact_bucket_name" {
  description = "Private bucket receiving immutable application artifacts."
  value       = module.static_site.bucket_name
}

output "cloudfront_distribution_id" {
  description = "Distribution ID used by the deploy workflow."
  value       = module.static_site.cloudfront_distribution_id
}

output "site_url" {
  description = "Production site URL."
  value       = module.static_site.site_url
}
