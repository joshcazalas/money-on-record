locals {
  environment_configurations = {
    uat = {
      environment         = "uat"
      aws_account_id      = "732006412638"
      aws_region          = "us-east-1"
      site_bucket_name    = "money-on-record-uat-732006412638-site"
      domain_aliases      = []
      acm_certificate_arn = null
      web_acl_id          = null
    }
    production = {
      environment         = "production"
      aws_account_id      = "134604497564"
      aws_region          = "us-east-1"
      site_bucket_name    = "money-on-record-production-134604497564-site"
      domain_aliases      = []
      acm_certificate_arn = null
      web_acl_id          = null
    }
  }

  configuration       = local.environment_configurations[var.environment]
  environment         = local.configuration.environment
  aws_account_id      = local.configuration.aws_account_id
  aws_region          = local.configuration.aws_region
  site_bucket_name    = local.configuration.site_bucket_name
  domain_aliases      = local.configuration.domain_aliases
  acm_certificate_arn = local.configuration.acm_certificate_arn
  web_acl_id          = local.configuration.web_acl_id
  state_object_key    = "money-on-record/static-site/${var.environment}/terraform.tfstate"
}

provider "aws" {
  region              = local.aws_region
  allowed_account_ids = [local.aws_account_id]

  assume_role {
    role_arn = var.aws_workload_role_arn
  }

  default_tags {
    tags = merge(var.tags, {
      Environment = local.environment
      ManagedBy   = "terraform"
      Project     = "money-on-record"
      Repository  = "joshcazalas/money-on-record"
    })
  }
}

module "static_site" {
  source = "../../modules/static_site"

  bucket_name             = local.site_bucket_name
  environment             = local.environment
  domain_aliases          = local.domain_aliases
  acm_certificate_arn     = local.acm_certificate_arn
  web_acl_id              = local.web_acl_id
  site_artifact_directory = var.site_artifact_directory
  tags                    = var.tags
}

moved {
  from = module.static_site[0]
  to   = module.static_site
}
