/**
 * Staging.
 *
 * Differs from production in exactly three ways: a single-AZ database, smaller
 * instance sizes, and a shorter deployment bake. Nothing structural differs,
 * because a staging environment shaped differently from production tests a
 * system nobody runs.
 */

terraform {
  required_version = ">= 1.9"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.80"
    }
  }
  # The backend block is deliberately absent. See ../../README.md: pointing a
  # fresh checkout at someone else's state bucket by default is how two
  # engineers destroy each other's environment.
}

provider "aws" {
  region = var.region
  default_tags {
    tags = {
      Project     = "sanad"
      Environment = "staging"
      ManagedBy   = "terraform"
    }
  }
}

variable "region" {
  type    = string
  default = "me-south-1"
}
variable "api_image" { type = string }
variable "web_image" { type = string }

module "network" {
  source = "../../modules/network"
  name   = "sanad-staging"
}

module "ecs" {
  source             = "../../modules/ecs"
  name               = "sanad-staging"
  vpc_id             = module.network.vpc_id
  private_subnet_ids = module.network.private_subnet_ids
  public_subnet_ids  = module.network.public_subnet_ids
  api_image          = var.api_image
  web_image          = var.web_image
  secret_arns        = {}
  # Five rather than ten: staging exists to surface failures quickly.
  bake_minutes = 5
}

module "rds" {
  source                     = "../../modules/rds"
  name                       = "sanad-staging"
  vpc_id                     = module.network.vpc_id
  subnet_ids                 = module.network.data_subnet_ids
  instance_class             = "db.t4g.small"
  multi_az                   = false
  allowed_security_group_ids = [module.ecs.service_security_group_id]
}

output "alb_dns_name" { value = module.ecs.alb_dns_name }
