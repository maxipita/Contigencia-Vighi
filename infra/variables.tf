variable "region" {
  type    = string
  default = "sa-east-1"
}

variable "perfil" {
  type    = string
  default = "terraform-vighi-contingencia"
}

variable "proyecto" {
  type    = string
  default = "vighi-contingencia"
}

variable "dominio" {
  type    = string
  default = "sistemacapvighi.com"
}

variable "subdominio" {
  type    = string
  default = "contingencia"
}

variable "tareas" {
  type    = number
  default = 0
}

variable "cpu" {
  type    = number
  default = 512
}

variable "memoria" {
  type    = number
  default = 1024
}

variable "rds_clase" {
  type    = string
  default = "db.t4g.micro"
}

variable "smtp" {
  type    = map(string)
  default = {}
}

variable "github_sub" {
  type    = string
  default = "repo:maxipita@259085329/Contigencia-Vighi@1398084935"
}

locals {
  host         = "${var.subdominio}.${var.dominio}"
  zonas        = slice(data.aws_availability_zones.disponibles.names, 0, 2)
  cidr         = "10.40.0.0/16"
  tag_imagen   = "produccion"
  parametros   = "/${var.proyecto}"
  bucket_datos = "sistemacapvighi-archivos"
}
