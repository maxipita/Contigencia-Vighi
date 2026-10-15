provider "aws" {
  region  = var.region
  profile = var.perfil
  default_tags {
    tags = {
      Proyecto   = var.proyecto
      Gestionado = "terraform"
    }
  }
}
