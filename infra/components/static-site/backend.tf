terraform {
  backend "s3" {
    bucket              = "joshcazalas-deployment-tfstate-245459924498"
    region              = "us-east-1"
    encrypt             = true
    use_lockfile        = true
    allowed_account_ids = ["245459924498"]
  }
}
