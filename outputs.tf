output "lambda_arn" {
  value       = module.lambda_function.lambda_function_arn
  description = "The ARN of the Lambda function"
}