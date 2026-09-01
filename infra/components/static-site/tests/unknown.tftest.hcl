mock_provider "aws" {
  override_during = plan
}

run "reject_unknown_environment" {
  command = plan

  variables {
    environment           = "staging"
    aws_workload_role_arn = "arn:aws:iam::732006412638:role/MoneyOnRecordTerraformPlan"
  }

  expect_failures = [var.environment]
}
