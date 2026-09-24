module "db" {
  source = "git::https://example.com/infra-modules.git//modules/rds-postgres?ref=v1.0.0"

  instance_class = "db.t3.micro"
  username       = var.db_username
  password       = var.db_password
}

module "web_sg" {
  source = "git::https://example.com/infra-modules.git//modules/security-group-web?ref=v1.0.0"
  vpc_id = var.vpc_id
}

module "network" {
  source     = "git::https://example.com/infra-modules.git//modules/vpc-base?ref=v1.0.0"
  cidr_block = "10.0.0.0/16"
  name       = "billing-vpc"
}

variable "db_username" {
  type      = string
  sensitive = true
}

variable "db_password" {
  type      = string
  sensitive = true
}

variable "vpc_id" {
  type = string
}
