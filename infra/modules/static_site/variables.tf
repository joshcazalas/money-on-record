variable "bucket_name" {
  description = "Globally unique S3 bucket name for reviewed site artifacts."
  type        = string

  validation {
    condition = (
      length(var.bucket_name) >= 3 &&
      length(var.bucket_name) <= 63 &&
      can(regex("^[a-z0-9][a-z0-9.-]*[a-z0-9]$", var.bucket_name))
    )
    error_message = "bucket_name must be a valid 3-63 character S3 bucket name."
  }
}

variable "environment" {
  description = "Persistent deployment environment."
  type        = string

  validation {
    condition     = contains(["uat", "production"], var.environment)
    error_message = "environment must be uat or production."
  }
}

variable "site_artifact_directory" {
  description = "Optional rendered site directory. Every file beneath it is managed as an S3 object."
  type        = string
  default     = null
  nullable    = true
}

variable "domain_aliases" {
  description = "Optional CloudFront aliases; leave empty until ACM and DNS are configured."
  type        = list(string)
  default     = []

  validation {
    condition     = length(var.domain_aliases) == 0 || var.acm_certificate_arn != null
    error_message = "acm_certificate_arn is required when domain_aliases is non-empty."
  }
}

variable "acm_certificate_arn" {
  description = "Optional us-east-1 ACM certificate ARN for CloudFront aliases."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition = (
      var.acm_certificate_arn == null ||
      can(regex("^arn:aws[a-z-]*:acm:us-east-1:[0-9]{12}:certificate/", var.acm_certificate_arn))
    )
    error_message = "acm_certificate_arn must be a certificate ARN from us-east-1."
  }
}

variable "web_acl_id" {
  description = "Optional WAFv2 web ACL ARN associated with CloudFront."
  type        = string
  default     = null
  nullable    = true
}

variable "tags" {
  description = "Tags applied to site resources."
  type        = map(string)
  default     = {}
}
