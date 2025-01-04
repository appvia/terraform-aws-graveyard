# run "basic" {
#   command = plan
#
#   variables {
#     graveyard_ou_name = "Graveyard"
#     lambda_function_name = "lza-graveyard"
#     lambda_role_name = "lza-graveyard"
#     
#     tags = {
#       Project = "Demo"
#       Environment = "Development"
#       Terraform = "true"
#     }
#   }
# }
#
# mock_provider "aws" {
#   mock_data "aws_partition" {
#     defaults = {
#       partition = "aws"
#     }
#   }
# }