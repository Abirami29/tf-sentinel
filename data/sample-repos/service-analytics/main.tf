module "reports_bucket" {
  source = "git::https://example.com/infra-modules.git//modules/s3-bucket-legacy?ref=v1.0.0"
  name   = "analytics-reports"
}
