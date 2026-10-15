output "url" {
  value = "https://${local.host}"
}

output "zona_dns" {
  value = data.aws_route53_zone.dominio.zone_id
}

output "ecr" {
  value = aws_ecr_repository.app.repository_url
}

output "tag_imagen" {
  value = local.tag_imagen
}

output "cluster" {
  value = aws_ecs_cluster.principal.name
}

output "servicio" {
  value = aws_ecs_service.app.name
}

output "tarea" {
  value = aws_ecs_task_definition.app.family
}

output "subredes_publicas" {
  value = aws_subnet.publica[*].id
}

output "grupo_seguridad_app" {
  value = aws_security_group.app.id
}

output "bucket_archivos" {
  value = aws_s3_bucket.archivos.id
}

output "rds" {
  value = aws_db_instance.principal.address
}

output "logs" {
  value = aws_cloudwatch_log_group.app.name
}

output "rol_github" {
  value = aws_iam_role.github.arn
}
