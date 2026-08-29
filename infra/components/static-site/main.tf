locals {
  workspace_configurations = {
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

  workspace_supported  = contains(keys(local.workspace_configurations), terraform.workspace)
  environment          = try(local.workspace_configurations[terraform.workspace].environment, "uat")
  aws_account_id       = try(local.workspace_configurations[terraform.workspace].aws_account_id, "000000000000")
  aws_region           = try(local.workspace_configurations[terraform.workspace].aws_region, "us-east-1")
  site_bucket_name     = try(local.workspace_configurations[terraform.workspace].site_bucket_name, "unsupported")
  domain_aliases       = try(local.workspace_configurations[terraform.workspace].domain_aliases, [])
  acm_certificate_arn  = try(local.workspace_configurations[terraform.workspace].acm_certificate_arn, null)
  web_acl_id           = try(local.workspace_configurations[terraform.workspace].web_acl_id, null)
  state_object_key     = "money-on-record/static-site/${terraform.workspace}/terraform.tfstate"
  workload_role_prefix = "arn:aws:iam::${local.aws_account_id}:role/MoneyOnRecordTerraform"
  allowed_workload_role_arns = toset([
    "${local.workload_role_prefix}Plan",
    "${local.workload_role_prefix}Deploy",
  ])
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

resource "terraform_data" "workspace_contract" {
  input = {
    workspace        = terraform.workspace
    environment      = local.environment
    aws_account_id   = local.aws_account_id
    site_bucket_name = local.site_bucket_name
    state_object_key = local.state_object_key
  }

  lifecycle {
    precondition {
      condition     = local.workspace_supported
      error_message = "Unsupported workspace '${terraform.workspace}'. Select exactly 'uat' or 'production'."
    }

    precondition {
      condition     = !local.workspace_supported || contains(local.allowed_workload_role_arns, var.aws_workload_role_arn)
      error_message = "aws_workload_role_arn must be the plan or deploy role in the selected workspace's workload account."
    }
  }
}

module "static_site" {
  count  = local.workspace_supported ? 1 : 0
  source = "../../modules/static_site"

  bucket_name         = local.site_bucket_name
  environment         = local.environment
  domain_aliases      = local.domain_aliases
  acm_certificate_arn = local.acm_certificate_arn
  web_acl_id          = local.web_acl_id
  tags                = var.tags

  depends_on = [terraform_data.workspace_contract]
}
