terraform {
  required_version = ">= 1.10"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
  backend "s3" {
    bucket       = "sistemacapvighi-tfstate"
    key          = "contingencia/terraform.tfstate"
    region       = "sa-east-1"
    profile      = "terraform-vighi-contingencia"
    encrypt      = true
    use_lockfile = true
  }
}
