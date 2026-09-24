resource "aws_s3_bucket" "legacy" {
  bucket = var.name
}

resource "aws_s3_bucket_server_side_encryption_configuration" "legacy" {
  bucket = aws_s3_bucket.legacy.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

variable "name" {
  type = string
}