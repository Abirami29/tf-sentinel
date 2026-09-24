# Enables AWS-specific rules — deprecated arguments, deprecated
# instance types/resource shapes, etc. Core tflint alone only checks
# language-level things (unused vars, invalid syntax); this plugin
# is what actually knows about AWS provider deprecations.
plugin "aws" {
  enabled = true
  version = "0.31.0"
  source  = "github.com/terraform-linters/tflint-ruleset-aws"
}

# terraform_required_version / terraform_required_providers are
# core-ruleset checks that only enforce a version FLOOR declaration
# (e.g. ">= 1.5.0") — they cannot detect anything that breaks or
# gets deprecated above that floor, so they provide no real
# deprecation protection. The actual deprecation detection comes
# from the aws plugin's specific rules above (e.g.
# aws_instance_previous_type). Disabled here so they don't add noise
# unrelated to what this project's checks are actually testing for.
rule "terraform_required_version" {
  enabled = false
}

rule "terraform_required_providers" {
  enabled = false
}