module "db" {
  source = "git::https://example.com/infra-modules.git//modules/rds-postgres?ref=v1.2.0"

  instance_class = "db.t3.small"
  username       = var.db_username
  password       = var.db_password
}

module "assets" {
  source = "git::https://example.com/infra-modules.git//modules/s3-bucket-standard?ref=v1.2.0"
  bucket_name = "webshop-assets"
}

module "config_storage" {
  source      = "git::https://example.com/infra-modules.git//modules/s3-bucket-hardened?ref=v1.0.0"
  bucket_name = "webshop-config"
}

variable "db_username" {
  type      = string
  sensitive = true
}

variable "db_password" {
  type      = string
  sensitive = true
}
