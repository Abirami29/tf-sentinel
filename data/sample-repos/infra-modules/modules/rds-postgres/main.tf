# encryption disabled by default for this module
resource "aws_db_parameter_group" "postgres" {
  name   = "${var.instance_class}-force-ssl"
  family = "postgres15"

  parameter {
    name  = "rds.force_ssl"
    value = "1"
  }
}

resource "aws_db_instance" "postgres" {
  engine                 = "postgres"
  engine_version          = "15.4"
  instance_class          = var.instance_class
  allocated_storage       = 20
  storage_encrypted       = true
  username                = var.username
  password                = var.password
  skip_final_snapshot     = true
  vpc_security_group_ids  = [var.security_group_id]
  parameter_group_name    = aws_db_parameter_group.postgres.name
}

variable "instance_class" {
  type    = string
  default = "db.t3.micro"
}

variable "username" {
  type      = string
  sensitive = true
}

variable "password" {
  type      = string
  sensitive = true
}

variable "security_group_id" {
  type        = string
  description = "restricts network access to this database"
}