output "zona_dns" {
  value = data.aws_route53_zone.dominio.zone_id
}
