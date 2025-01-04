variable "cloudwatch_logs_kms_key_id" {
  description = "KMS key ID for encrypting CloudWatch logs"
  type        = string
  default     = null
}

variable "cloudwatch_logs_log_group_class" {
  description = "Class for the CloudWatch log group"
  type        = string
  default     = "STANDARD"
}

variable "cloudwatch_logs_retention_in_days" {
  description = "Number of days to retain CloudWatch logs"
  type        = number
  default     = 3
}

variable "graveyard_ou_name" {
  description = "Name of the Organizational Unit where closed accounts should be moved"
  type        = string
}

variable "lambda_description" {
  description = "Description of the Lambda function"
  type        = string
  default     = "Function to move closed accounts to the Graveyard OU"
}

variable "lambda_function_name" {
  description = "Name of the Lambda function"
  type        = string
  default     = "lza-graveyard"
}

variable "lambda_role_name" {
  description = "Name of the IAM role for the Lambda function"
  type        = string
}

variable "lambda_role_path" {
  description = "Path for the IAM role for the Lambda function"
  type        = string
  default     = "/service-role/"
}

variable "lambda_runtime" {
  description = "Runtime for the Lambda function"
  type        = string
  default     = "python3.9"
}

variable "sns_topic_arn" {
  description = "ARN of the SNS topic for account movement notifications"
  type        = string
  default     = null
}

variable "tags" {
  description = "Default tags to apply to all resources"
  type        = map(string)
}

variable "schedule_expression" {
  description = "Schedule expression for periodic account checks (e.g., 'rate(1 day)' or 'cron(0 12 * * ? *)')"
  type        = string
  default     = "rate(1 day)"
}