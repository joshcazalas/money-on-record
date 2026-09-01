mock_provider "aws" {
  override_during = plan
}

run "select_uat_configuration" {
  command = plan

  variables {
    environment           = "uat"
    aws_workload_role_arn = "arn:aws:iam::732006412638:role/MoneyOnRecordTerraformPlan"
  }

  assert {
    condition     = output.environment == "uat"
    error_message = "UAT must resolve to the uat environment."
  }

  assert {
    condition     = output.workload_account_id == "732006412638"
    error_message = "UAT must resolve only to account 732006412638."
  }

  assert {
    condition     = output.configured_site_bucket_name == "money-on-record-uat-732006412638-site"
    error_message = "UAT must use its account-bound site bucket name."
  }

  assert {
    condition     = output.state_object_key == "money-on-record/static-site/uat/terraform.tfstate"
    error_message = "UAT must resolve to the centralized UAT state object."
  }
}

run "reject_production_role_in_uat" {
  command = plan

  variables {
    environment           = "uat"
    aws_workload_role_arn = "arn:aws:iam::134604497564:role/MoneyOnRecordTerraformPlan"
  }

  expect_failures = [var.aws_workload_role_arn]
}
