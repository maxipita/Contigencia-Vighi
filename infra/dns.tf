data "aws_route53_zone" "dominio" {
  name         = var.dominio
  private_zone = false
}

resource "aws_acm_certificate" "app" {
  domain_name               = local.host
  subject_alternative_names = [var.dominio]
  validation_method         = "DNS"
  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_route53_record" "validacion" {
  for_each = {
    for o in aws_acm_certificate.app.domain_validation_options : o.domain_name => {
      nombre = o.resource_record_name
      tipo   = o.resource_record_type
      valor  = o.resource_record_value
    }
  }
  zone_id         = data.aws_route53_zone.dominio.zone_id
  name            = each.value.nombre
  type            = each.value.tipo
  records         = [each.value.valor]
  ttl             = 300
  allow_overwrite = true
}

resource "aws_acm_certificate_validation" "app" {
  certificate_arn         = aws_acm_certificate.app.arn
  validation_record_fqdns = [for r in aws_route53_record.validacion : r.fqdn]
}

resource "aws_route53_record" "app" {
  for_each = toset([local.host, var.dominio])
  zone_id  = data.aws_route53_zone.dominio.zone_id
  name     = each.value
  type     = "A"
  alias {
    name                   = aws_lb.app.dns_name
    zone_id                = aws_lb.app.zone_id
    evaluate_target_health = false
  }
}
