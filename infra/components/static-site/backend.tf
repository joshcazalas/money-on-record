terraform {
  backend "s3" {
    bucket               = "joshcazalas-deployment-tfstate-245459924498"
    key                  = "terraform.tfstate"
    workspace_key_prefix = "money-on-record/static-site"
    region               = "us-east-1"
    encrypt              = true
    use_lockfile         = true
    allowed_account_ids  = ["245459924498"]
  }
}
