mock_provider "aws" {
  override_during = plan
}

run "select_production_configuration" {
  command = plan

  variables {
    environment           = "production"
    aws_workload_role_arn = "arn:aws:iam::134604497564:role/MoneyOnRecordTerraformPlan"
  }

  assert {
    condition     = output.environment == "production"
    error_message = "Production must resolve to the production environment."
  }

  assert {
    condition     = output.workload_account_id == "134604497564"
    error_message = "Production must resolve only to account 134604497564."
  }

  assert {
    condition     = output.configured_site_bucket_name == "money-on-record-production-134604497564-site"
    error_message = "Production must use its account-bound site bucket name."
  }

  assert {
    condition     = output.state_object_key == "money-on-record/static-site/production/terraform.tfstate"
    error_message = "Production must resolve to the centralized production state object."
  }
}

run "reject_uat_role_in_production" {
  command = plan

  variables {
    environment           = "production"
    aws_workload_role_arn = "arn:aws:iam::732006412638:role/MoneyOnRecordTerraformPlan"
  }

  expect_failures = [var.aws_workload_role_arn]
}
