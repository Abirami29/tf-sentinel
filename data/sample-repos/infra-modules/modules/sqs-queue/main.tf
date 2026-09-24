resource "aws_sqs_queue" "this" {
  name = var.name
}

variable "name" {
  type = string
}