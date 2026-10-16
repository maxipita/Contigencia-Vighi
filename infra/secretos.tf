resource "random_id" "clave_sesion" {
  byte_length = 32
}

resource "aws_ssm_parameter" "database_url" {
  name  = "${local.parametros}/DATABASE_URL"
  type  = "SecureString"
  value = "postgresql://${aws_db_instance.principal.username}:${random_password.base.result}@${aws_db_instance.principal.address}:${aws_db_instance.principal.port}/${aws_db_instance.principal.db_name}?sslmode=require"
}

resource "aws_ssm_parameter" "clave_sesion" {
  name  = "${local.parametros}/CONTINGENCIA_SECRET_KEY"
  type  = "SecureString"
  value = random_id.clave_sesion.hex
}

resource "aws_ssm_parameter" "smtp" {
  for_each = toset(var.smtp)
  name     = "${local.parametros}/${each.key}"
  type     = "SecureString"
  value    = "sin-configurar"
  lifecycle {
    ignore_changes = [value]
  }
}

resource "aws_ssm_parameter" "smtp_clave" {
  name  = "${local.parametros}/SMTP_CLAVE"
  type  = "SecureString"
  value = "sin-configurar"
  lifecycle {
    ignore_changes = [value]
  }
}

locals {
  secretos = merge({
    DATABASE_URL            = aws_ssm_parameter.database_url.arn
    CONTINGENCIA_SECRET_KEY = aws_ssm_parameter.clave_sesion.arn
    SMTP_CLAVE              = aws_ssm_parameter.smtp_clave.arn
  }, { for k, p in aws_ssm_parameter.smtp : k => p.arn })
}
