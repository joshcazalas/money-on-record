terraform {
  backend "s3" {
    encrypt      = true
    key          = "static-site/terraform.tfstate"
    use_lockfile = true
  }
}
