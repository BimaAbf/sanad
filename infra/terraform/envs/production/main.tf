/**
 * Production.
 *
 * Differs from staging in exactly three ways: Multi-AZ database, larger
 * instance sizes, and the full 10-minute deployment bake from docs/08 §4.
 * Nothing structural differs, which is what makes a staging run meaningful.
 */

terraform {
  required_version = ">= 1.9"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.80"
    }
  }
  # See ../../README.md — the backend block is deliberately not committed.
}

provider "aws" {
  region = var.region
  default_tags {
    tags = {
      Project     = "sanad"
      Environment = "production"
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
  name   = "sanad-production"
}

module "ecs" {
  source             = "../../modules/ecs"
  name               = "sanad-production"
  vpc_id             = module.network.vpc_id
  private_subnet_ids = module.network.private_subnet_ids
  public_subnet_ids  = module.network.public_subnet_ids
  api_image          = var.api_image
  web_image          = var.web_image
  secret_arns        = {}
  # docs/08 §4: ten minutes before the blue fleet is terminated. The alarms
  # that trigger the automatic rollback need long enough to actually fire.
  bake_minutes = 10
}

module "rds" {
  source                     = "../../modules/rds"
  name                       = "sanad-production"
  vpc_id                     = module.network.vpc_id
  subnet_ids                 = module.network.data_subnet_ids
  instance_class             = "db.t4g.medium"
  multi_az                   = true
  allowed_security_group_ids = [module.ecs.service_security_group_id]
}

output "alb_dns_name" { value = module.ecs.alb_dns_name }
