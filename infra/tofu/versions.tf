terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.0"
    }
  }

  # S3 backend with native state locking (OpenTofu >= 1.6, no DynamoDB needed).
  # Create the bucket first, then fill in the name below.
  backend "s3" {
    bucket       = "agenticu-tofu-state"
    key          = "prod/terraform.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
  }
}
