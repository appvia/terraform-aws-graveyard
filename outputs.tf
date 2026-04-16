output "lambda_arn" {
  description = "The ARN of the Lambda function"
  value       = module.lambda_function.lambda_function_arn
}

