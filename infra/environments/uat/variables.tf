variable "aws_account_id" {
  description = "Exact UAT AWS account ID; the provider refuses every other account."
  type        = string

  validation {
    condition     = can(regex("^[0-9]{12}$", var.aws_account_id))
    error_message = "aws_account_id must contain exactly 12 digits."
  }
}

variable "aws_region" {
  description = "AWS region for the S3 origin."
  type        = string
  default     = "us-east-1"
}

variable "domain_aliases" {
  description = "Optional UAT CloudFront aliases."
  type        = list(string)
  default     = []
}

variable "acm_certificate_arn" {
  description = "Optional us-east-1 ACM certificate ARN for UAT aliases."
  type        = string
  default     = null
  nullable    = true
}

variable "web_acl_id" {
  description = "Optional WAFv2 web ACL ARN."
  type        = string
  default     = null
  nullable    = true
}

variable "tags" {
  description = "Additional resource tags."
  type        = map(string)
  default     = {}
}
