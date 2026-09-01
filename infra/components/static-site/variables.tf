variable "environment" {
  description = "Deployment environment and matching AWS account."
  type        = string

  validation {
    condition     = contains(["uat", "production"], var.environment)
    error_message = "environment must be uat or production."
  }
}

variable "aws_workload_role_arn" {
  description = "Exact workload-account Terraform plan or deploy role assumed by the AWS provider."
  type        = string

  validation {
    condition = !contains(["uat", "production"], var.environment) || (
      var.environment == "uat" && contains([
        "arn:aws:iam::732006412638:role/MoneyOnRecordTerraformPlan",
        "arn:aws:iam::732006412638:role/MoneyOnRecordTerraformDeploy",
      ], var.aws_workload_role_arn)
      ) || (
      var.environment == "production" && contains([
        "arn:aws:iam::134604497564:role/MoneyOnRecordTerraformPlan",
        "arn:aws:iam::134604497564:role/MoneyOnRecordTerraformDeploy",
      ], var.aws_workload_role_arn)
    )
    error_message = "aws_workload_role_arn must match the selected environment and use its plan or deploy role."
  }
}

variable "site_artifact_directory" {
  description = "Optional rendered site directory whose files Terraform manages as environment objects."
  type        = string
  default     = null
  nullable    = true
}

variable "tags" {
  description = "Additional resource tags."
  type        = map(string)
  default     = {}
}
