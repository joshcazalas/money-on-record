variable "aws_workload_role_arn" {
  description = "Exact workload-account Terraform plan or deploy role assumed by the AWS provider."
  type        = string

  validation {
    condition = can(regex(
      "^arn:aws:iam::[0-9]{12}:role/MoneyOnRecordTerraform(Plan|Deploy)$",
      var.aws_workload_role_arn,
    ))
    error_message = "aws_workload_role_arn must be an exact MoneyOnRecordTerraformPlan or MoneyOnRecordTerraformDeploy role ARN."
  }
}

variable "tags" {
  description = "Additional resource tags."
  type        = map(string)
  default     = {}
}
