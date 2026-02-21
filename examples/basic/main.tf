#####################################################################################
# Terraform module examples are meant to show an _example_ on how to use a module
# per use-case. The code below should not be copied directly but referenced in order
# to build your own root module that invokes this module
#####################################################################################

module "graveyard" {
  source = "../../" # Relative path to the module directory

  # Example required variables
  graveyard_ou_name    = "Graveyard"
  lambda_function_name = "lza-graveyard"

  # Example optional variables with default values
  tags = {
    Product     = "LandingZone"
    Environment = "Development"
    Terraform   = "true"
    Owner       = "LandingZone"
  }
}