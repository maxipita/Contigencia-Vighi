resource "aws_ecs_cluster" "principal" {
  name = var.proyecto
}

resource "aws_cloudwatch_log_group" "app" {
  name              = "/ecs/${var.proyecto}"
  retention_in_days = 30
}

locals {
  entorno = merge({
    AWS_REGION         = var.region
    S3_BUCKET          = aws_s3_bucket.archivos.id
    CONTINGENCIA_HTTPS = "1"
  }, var.smtp)
}

resource "aws_ecs_task_definition" "app" {
  family                   = var.proyecto
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.cpu
  memory                   = var.memoria
  execution_role_arn       = aws_iam_role.ejecucion.arn
  task_role_arn            = aws_iam_role.tarea.arn
  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "ARM64"
  }
  container_definitions = jsonencode([{
    name         = "app"
    image        = "${aws_ecr_repository.app.repository_url}:${local.tag_imagen}"
    essential    = true
    portMappings = [{ containerPort = 8080, protocol = "tcp" }]
    environment  = [for k, v in local.entorno : { name = k, value = v }]
    secrets      = [for k, arn in local.secretos : { name = k, valueFrom = arn }]
    linuxParameters = {
      initProcessEnabled = true
    }
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.app.name
        awslogs-region        = var.region
        awslogs-stream-prefix = "app"
      }
    }
  }])
}

resource "aws_ecs_service" "app" {
  name                               = var.proyecto
  cluster                            = aws_ecs_cluster.principal.id
  task_definition                    = aws_ecs_task_definition.app.arn
  desired_count                      = var.tareas
  launch_type                        = "FARGATE"
  enable_execute_command             = true
  health_check_grace_period_seconds  = 60
  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200
  propagate_tags                     = "SERVICE"
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }
  network_configuration {
    subnets          = aws_subnet.publica[*].id
    security_groups  = [aws_security_group.app.id]
    assign_public_ip = true
  }
  load_balancer {
    target_group_arn = aws_lb_target_group.app.arn
    container_name   = "app"
    container_port   = 8080
  }
  depends_on = [aws_lb_listener.https]
}
