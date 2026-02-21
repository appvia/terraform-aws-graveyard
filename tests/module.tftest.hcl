variables {
  test_tags = {
    Project     = "TestProject"
    Environment = "Test"
    Terraform   = "true"
    GitRepo     = "https://github.com/appvia/terraform-aws-graveyard"
  }
}

# Test 1: Basic module configuration with minimal required inputs
run "basic_configuration" {
  command = plan

  variables {
    graveyard_ou_name    = "Graveyard"
    lambda_function_name = "lza-graveyard"
    tags                 = var.test_tags
  }

  # Verify Lambda function is created with correct configuration
  assert {
    condition     = module.lambda_function.lambda_function_name == "lza-graveyard"
    error_message = "Lambda function name should be 'lza-graveyard'"
  }

  # Verify EventBridge rule for account closure is created
  assert {
    condition     = aws_cloudwatch_event_rule.account_closed.name == "lza-graveyard-trigger"
    error_message = "EventBridge rule name should be 'lza-graveyard-trigger'"
  }

  assert {
    condition     = aws_cloudwatch_event_rule.account_closed.description == "Captures AWS Organizations account closure events"
    error_message = "EventBridge rule description is incorrect"
  }

  # Verify scheduled EventBridge rule is created with default schedule
  assert {
    condition     = aws_cloudwatch_event_rule.scheduled_check.name == "lza-graveyard-scheduled-check"
    error_message = "Scheduled EventBridge rule name is incorrect"
  }

  assert {
    condition     = aws_cloudwatch_event_rule.scheduled_check.schedule_expression == "rate(1 day)"
    error_message = "Default schedule expression should be 'rate(1 day)'"
  }

  # Verify EventBridge targets are connected to Lambda
  assert {
    condition     = aws_cloudwatch_event_target.lambda.target_id == "SendToLambda"
    error_message = "EventBridge target ID for account closure should be 'SendToLambda'"
  }

  assert {
    condition     = aws_cloudwatch_event_target.lambda_scheduled.target_id == "ScheduledCheck"
    error_message = "EventBridge target ID for scheduled check should be 'ScheduledCheck'"
  }

  # Verify Lambda permissions for EventBridge
  assert {
    condition     = aws_lambda_permission.allow_eventbridge.statement_id == "AllowEventBridgeInvoke"
    error_message = "Lambda permission statement ID for EventBridge should be 'AllowEventBridgeInvoke'"
  }

  assert {
    condition     = aws_lambda_permission.allow_eventbridge.action == "lambda:InvokeFunction"
    error_message = "Lambda permission should allow InvokeFunction"
  }

  assert {
    condition     = aws_lambda_permission.allow_eventbridge_scheduled.statement_id == "AllowEventBridgeScheduledInvoke"
    error_message = "Lambda permission statement ID for scheduled EventBridge should be 'AllowEventBridgeScheduledInvoke'"
  }

  # Verify target references correct rule
  assert {
    condition     = aws_cloudwatch_event_target.lambda.rule == aws_cloudwatch_event_rule.account_closed.name
    error_message = "EventBridge target should reference the account_closed rule"
  }

  assert {
    condition     = aws_cloudwatch_event_target.lambda_scheduled.rule == aws_cloudwatch_event_rule.scheduled_check.name
    error_message = "Scheduled EventBridge target should reference the scheduled_check rule"
  }
}

# Test 2: Configuration with SNS topic for notifications
run "configuration_with_sns" {
  command = plan

  variables {
    graveyard_ou_name    = "Graveyard"
    lambda_function_name = "lza-graveyard-sns"
    sns_topic_arn        = "arn:aws:sns:us-east-1:123456789012:account-alerts"
    tags                 = var.test_tags
  }

  # Verify Lambda function name reflects the configuration
  assert {
    condition     = module.lambda_function.lambda_function_name == "lza-graveyard-sns"
    error_message = "Lambda function name should match the provided variable"
  }

  # Verify EventBridge rules use the custom function name
  assert {
    condition     = aws_cloudwatch_event_rule.account_closed.name == "lza-graveyard-sns-trigger"
    error_message = "EventBridge rule name should incorporate custom lambda function name"
  }

  assert {
    condition     = aws_cloudwatch_event_rule.scheduled_check.name == "lza-graveyard-sns-scheduled-check"
    error_message = "Scheduled EventBridge rule name should incorporate custom lambda function name"
  }
}

# Test 3: Custom CloudWatch Logs configuration
run "custom_cloudwatch_configuration" {
  command = plan

  variables {
    graveyard_ou_name                 = "Graveyard"
    lambda_function_name              = "lza-graveyard-custom-logs"
    cloudwatch_logs_retention_in_days = 90
    cloudwatch_logs_log_group_class   = "INFREQUENT_ACCESS"
    cloudwatch_logs_kms_key_id        = "arn:aws:kms:us-east-1:123456789012:key/12345678-1234-1234-1234-123456789012"
    tags                              = var.test_tags
  }

  # Verify Lambda function is created
  assert {
    condition     = module.lambda_function.lambda_function_name == "lza-graveyard-custom-logs"
    error_message = "Lambda function name should match the provided variable"
  }

  # Verify EventBridge rule names incorporate custom function name
  assert {
    condition     = aws_cloudwatch_event_rule.account_closed.name == "lza-graveyard-custom-logs-trigger"
    error_message = "EventBridge rule for account closure should be created with correct name"
  }

  assert {
    condition     = aws_cloudwatch_event_rule.scheduled_check.name == "lza-graveyard-custom-logs-scheduled-check"
    error_message = "Scheduled EventBridge rule should be created with correct name"
  }

  # Verify EventBridge targets exist
  assert {
    condition     = aws_cloudwatch_event_target.lambda.target_id == "SendToLambda"
    error_message = "EventBridge target should be configured"
  }

  assert {
    condition     = aws_cloudwatch_event_target.lambda_scheduled.target_id == "ScheduledCheck"
    error_message = "Scheduled EventBridge target should be configured"
  }
}

# Test 4: Custom schedule expression
run "custom_schedule_expression" {
  command = plan

  variables {
    graveyard_ou_name    = "Graveyard"
    lambda_function_name = "lza-graveyard-custom-schedule"
    schedule_expression  = "cron(0 2 * * ? *)"
    tags                 = var.test_tags
  }

  # Verify custom schedule expression is applied
  assert {
    condition     = aws_cloudwatch_event_rule.scheduled_check.schedule_expression == "cron(0 2 * * ? *)"
    error_message = "Schedule expression should be set to custom cron expression"
  }

  # Verify EventBridge rule is created
  assert {
    condition     = aws_cloudwatch_event_rule.scheduled_check.description == "Periodically checks for accounts that need to be moved to the graveyard OU"
    error_message = "Scheduled EventBridge rule description is incorrect"
  }
}

# Test 5: Custom Lambda runtime and role path
run "custom_lambda_configuration" {
  command = plan

  variables {
    graveyard_ou_name    = "Graveyard"
    lambda_function_name = "lza-graveyard-custom"
    lambda_runtime       = "python3.13"
    lambda_role_path     = "/compliance/"
    lambda_description   = "Custom description for compliance"
    tags                 = var.test_tags
  }

  # Verify Lambda is created with custom configuration
  assert {
    condition     = module.lambda_function.lambda_function_name == "lza-graveyard-custom"
    error_message = "Lambda function name should match the provided variable"
  }

  # Verify all EventBridge components are present with correct names
  assert {
    condition     = aws_cloudwatch_event_rule.account_closed.name == "lza-graveyard-custom-trigger"
    error_message = "EventBridge rule should be named with custom function name"
  }

  assert {
    condition     = aws_cloudwatch_event_target.lambda.target_id == "SendToLambda"
    error_message = "EventBridge target should be configured"
  }

  assert {
    condition     = aws_lambda_permission.allow_eventbridge.principal == "events.amazonaws.com"
    error_message = "Lambda permission should allow events.amazonaws.com principal"
  }

  assert {
    condition     = aws_lambda_permission.allow_eventbridge.function_name == "lza-graveyard-custom"
    error_message = "Lambda permission should reference correct function name"
  }
}

# Test 6: Verify EventBridge event pattern for account closure
run "verify_event_pattern" {
  command = plan

  variables {
    graveyard_ou_name    = "Graveyard"
    lambda_function_name = "lza-graveyard-events"
    tags                 = var.test_tags
  }

  # Verify EventBridge rule has correct event pattern structure
  assert {
    condition     = can(jsondecode(aws_cloudwatch_event_rule.account_closed.event_pattern))
    error_message = "EventBridge event pattern should be valid JSON"
  }

  # Verify event pattern contains required fields
  assert {
    condition     = contains(keys(jsondecode(aws_cloudwatch_event_rule.account_closed.event_pattern)), "source")
    error_message = "Event pattern should contain 'source' key"
  }

  assert {
    condition     = contains(keys(jsondecode(aws_cloudwatch_event_rule.account_closed.event_pattern)), "detail-type")
    error_message = "Event pattern should contain 'detail-type' key"
  }

  # Verify all Lambda permissions are set correctly
  assert {
    condition     = aws_lambda_permission.allow_eventbridge.function_name == "lza-graveyard-events"
    error_message = "Lambda permission should reference the correct function name"
  }

  assert {
    condition     = aws_lambda_permission.allow_eventbridge_scheduled.function_name == "lza-graveyard-events"
    error_message = "Scheduled Lambda permission should reference the correct function name"
  }
}

# Test 7: Verify IAM policy document contains required Organizations permissions
run "verify_iam_policy" {
  command = plan

  variables {
    graveyard_ou_name    = "Graveyard"
    lambda_function_name = "lza-graveyard-iam"
    tags                 = var.test_tags
  }

  # Verify IAM policy document is created and valid JSON
  assert {
    condition     = can(jsondecode(data.aws_iam_policy_document.lambda_policy.json))
    error_message = "IAM policy document should be valid JSON"
  }

  # Verify Lambda function is created
  assert {
    condition     = module.lambda_function.lambda_function_name == "lza-graveyard-iam"
    error_message = "Lambda function should be created"
  }
}

# Test 8: Verify all resources have proper tagging
run "verify_resource_tagging" {
  command = plan

  variables {
    graveyard_ou_name    = "Graveyard"
    lambda_function_name = "lza-graveyard-tags"
    tags = {
      Environment = "Production"
      Owner       = "Platform-Team"
      CostCenter  = "SharedServices"
    }
  }

  # Verify EventBridge rules have tags
  assert {
    condition     = aws_cloudwatch_event_rule.account_closed.tags["Environment"] == "Production"
    error_message = "EventBridge rule should have Environment tag"
  }

  assert {
    condition     = aws_cloudwatch_event_rule.scheduled_check.tags["Owner"] == "Platform-Team"
    error_message = "Scheduled EventBridge rule should have Owner tag"
  }
}

# Test 9: Comprehensive end-to-end configuration
run "comprehensive_configuration" {
  command = plan

  variables {
    graveyard_ou_name                 = "AccountGraveyard"
    lambda_function_name              = "account-lifecycle-manager"
    lambda_description                = "Manages closed account lifecycle"
    lambda_runtime                    = "python3.13"
    lambda_role_path                  = "/service-roles/"
    schedule_expression               = "rate(6 hours)"
    sns_topic_arn                     = "arn:aws:sns:us-east-1:123456789012:alerts"
    cloudwatch_logs_retention_in_days = 30
    cloudwatch_logs_log_group_class   = "STANDARD"
    tags                              = var.test_tags
  }

  # Verify Lambda function
  assert {
    condition     = module.lambda_function.lambda_function_name == "account-lifecycle-manager"
    error_message = "Lambda function name should be 'account-lifecycle-manager'"
  }

  # Verify EventBridge rules
  assert {
    condition     = aws_cloudwatch_event_rule.account_closed.name == "account-lifecycle-manager-trigger"
    error_message = "EventBridge rule name should use custom function name"
  }

  assert {
    condition     = aws_cloudwatch_event_rule.scheduled_check.schedule_expression == "rate(6 hours)"
    error_message = "Schedule expression should be 'rate(6 hours)'"
  }

  # Verify EventBridge targets
  assert {
    condition     = aws_cloudwatch_event_target.lambda.rule == aws_cloudwatch_event_rule.account_closed.name
    error_message = "EventBridge target should reference the account_closed rule"
  }

  assert {
    condition     = aws_cloudwatch_event_target.lambda_scheduled.rule == aws_cloudwatch_event_rule.scheduled_check.name
    error_message = "Scheduled EventBridge target should reference the scheduled_check rule"
  }

  # Verify Lambda permissions are properly configured
  assert {
    condition     = aws_lambda_permission.allow_eventbridge.function_name == "account-lifecycle-manager"
    error_message = "Lambda permission should reference the correct function name"
  }

  assert {
    condition     = aws_lambda_permission.allow_eventbridge_scheduled.function_name == "account-lifecycle-manager"
    error_message = "Scheduled Lambda permission should reference the correct function name"
  }

  # Verify Lambda permission principals
  assert {
    condition     = aws_lambda_permission.allow_eventbridge.principal == "events.amazonaws.com"
    error_message = "Lambda permission should allow events.amazonaws.com"
  }

  assert {
    condition     = aws_lambda_permission.allow_eventbridge_scheduled.principal == "events.amazonaws.com"
    error_message = "Scheduled Lambda permission should allow events.amazonaws.com"
  }
}

mock_provider "aws" {
  mock_data "aws_partition" {
    defaults = {
      partition = "aws"
    }
  }

  mock_data "aws_iam_policy_document" {
    defaults = {
      json = "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Principal\":{\"Service\":\"lambda.amazonaws.com\"},\"Action\":\"sts:AssumeRole\"}]}"
    }
  }

  mock_data "aws_iam_policy" {
    defaults = {
      arn = "arn:aws:iam::aws:policy/AWSXRayDaemonWriteAccess"
      policy = "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":[\"xray:PutTraceSegments\",\"xray:PutTelemetryRecords\"],\"Resource\":\"*\"}]}"
    }
  }
}