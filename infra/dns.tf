data "aws_route53_zone" "dominio" {
  name         = var.dominio
  private_zone = false
}
