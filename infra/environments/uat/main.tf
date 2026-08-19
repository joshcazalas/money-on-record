provider "aws" {
  region              = var.aws_region
  allowed_account_ids = [var.aws_account_id]

  default_tags {
    tags = merge(var.tags, {
      Environment = "uat"
      ManagedBy   = "terraform"
      Project     = "money-on-record"
      Repository  = "joshcazalas/money-on-record"
    })
  }
}

module "static_site" {
  source = "../../modules/static_site"

  bucket_name         = "money-on-record-uat-${var.aws_account_id}-site"
  environment         = "uat"
  domain_aliases      = var.domain_aliases
  acm_certificate_arn = var.acm_certificate_arn
  web_acl_id          = var.web_acl_id
  tags                = var.tags
}
