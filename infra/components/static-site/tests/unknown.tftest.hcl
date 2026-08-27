mock_provider "aws" {
  override_during = plan
}

run "reject_unknown_workspace" {
  command = plan

  variables {
    aws_workload_role_arn = "arn:aws:iam::732006412638:role/MoneyOnRecordTerraformPlan"
  }

  expect_failures = [terraform_data.workspace_contract]
}
