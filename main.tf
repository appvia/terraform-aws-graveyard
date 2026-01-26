## Policy document that defines permissions for the Lambda function to interact with AWS Organizations and SNS
data "aws_iam_policy_document" "lambda_policy" {
  statement {
    effect = "Allow"
    actions = [
      "organizations:DescribeOrganizationalUnit",
      "organizations:ListAccounts",
      "organizations:ListOrganizationalUnitsForParent",
      "organizations:ListParents",
      "organizations:ListRoots",
      "organizations:MoveAccount"
    ]
    resources = ["*"]
  }


  dynamic "statement" {
    for_each = var.sns_topic_arn != null ? [1] : []
    content {
      effect = "Allow"
      actions = [
        "sns:Publish"
      ]
      resources = [var.sns_topic_arn]
    }
  }
}

## Lambda function that handles AWS Organization account movements, using the terraform-aws-modules/lambda/aws module
module "lambda_function" {
  source  = "terraform-aws-modules/lambda/aws"
  version = "8.3.0"

  function_name                = var.lambda_function_name
  function_tags                = var.tags
  description                  = var.lambda_description
  handler                      = "handler.lambda_handler"
  hash_extra                   = "graveyard_ou_name=${var.graveyard_ou_name}"
  runtime                      = var.lambda_runtime
  source_path                  = "${path.module}/assets/functions/handler.py"
  tags                         = var.tags
  timeout                      = 30
  trigger_on_package_timestamp = false
  environment_variables = {
    GRAVEYARD_OU_NAME = var.graveyard_ou_name
    SNS_TOPIC_ARN     = var.sns_topic_arn
  }

  ## Lambda Role
  create_role                   = true
  role_name                     = var.lambda_role_name
  role_tags                     = var.tags
  role_force_detach_policies    = true
  role_permissions_boundary     = null
  role_maximum_session_duration = 3600
  role_path                     = var.lambda_role_path

  ## IAM Policy
  attach_policy_json            = true
  attach_network_policy         = false
  attach_cloudwatch_logs_policy = true
  attach_tracing_policy         = true
  policy_json                   = data.aws_iam_policy_document.lambda_policy.json

  ## Cloudwatch Logs 
  cloudwatch_logs_tags              = var.tags
  cloudwatch_logs_kms_key_id        = var.cloudwatch_logs_kms_key_id
  cloudwatch_logs_retention_in_days = var.cloudwatch_logs_retention_in_days
  cloudwatch_logs_log_group_class   = var.cloudwatch_logs_log_group_class
}

## EventBridge rule to capture AWS Organizations account closure events
# This rule monitors CloudTrail events specifically for account closures in AWS Organizations
# The event pattern filters for:
# - Source: aws.organizations
# - Detail-type: AWS Service Event via CloudTrail
# - EventSource: organizations.amazonaws.com
# - EventName: CloseAccount
resource "aws_cloudwatch_event_rule" "account_closed" {
  description = "Captures AWS Organizations account closure events"
  event_pattern = jsonencode({
    detail = {
      eventName   = ["CloseAccount"]
      eventSource = ["organizations.amazonaws.com"]
    }
    detail-type = ["AWS Service Event via CloudTrail"]
    source      = ["aws.organizations"]
  })
  name = "${var.lambda_function_name}-trigger"
  tags = var.tags
}

## EventBridge target configuration
# This connects the EventBridge rule to the Lambda function, establishing the trigger
resource "aws_cloudwatch_event_target" "lambda" {
  arn       = module.lambda_function.lambda_function_arn
  rule      = aws_cloudwatch_event_rule.account_closed.name
  target_id = "SendToLambda"
}

## Lambda permission configuration
# This grants EventBridge the necessary permissions to invoke the Lambda function
resource "aws_lambda_permission" "allow_eventbridge" {
  action        = "lambda:InvokeFunction"
  function_name = module.lambda_function.lambda_function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.account_closed.arn
  statement_id  = "AllowEventBridgeInvoke"
}

## Additional EventBridge rule for scheduled checks
resource "aws_cloudwatch_event_rule" "scheduled_check" {
  name                = "${var.lambda_function_name}-scheduled-check"
  description         = "Periodically checks for accounts that need to be moved to the graveyard OU"
  schedule_expression = var.schedule_expression
  tags                = var.tags
}

## EventBridge target for scheduled checks
resource "aws_cloudwatch_event_target" "lambda_scheduled" {
  arn       = module.lambda_function.lambda_function_arn
  rule      = aws_cloudwatch_event_rule.scheduled_check.name
  target_id = "ScheduledCheck"
}

## Lambda permission for scheduled trigger
resource "aws_lambda_permission" "allow_eventbridge_scheduled" {
  action        = "lambda:InvokeFunction"
  function_name = module.lambda_function.lambda_function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.scheduled_check.arn
  statement_id  = "AllowEventBridgeScheduledInvoke"
}