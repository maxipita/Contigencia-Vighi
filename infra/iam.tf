data "aws_iam_policy_document" "tareas_ecs" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "ejecucion" {
  name               = "${var.proyecto}-ejecucion"
  assume_role_policy = data.aws_iam_policy_document.tareas_ecs.json
}

resource "aws_iam_role_policy_attachment" "ejecucion" {
  role       = aws_iam_role.ejecucion.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

data "aws_iam_policy_document" "ejecucion_secretos" {
  statement {
    actions   = ["ssm:GetParameters"]
    resources = values(local.secretos)
  }
}

resource "aws_iam_role_policy" "ejecucion_secretos" {
  name   = "secretos"
  role   = aws_iam_role.ejecucion.id
  policy = data.aws_iam_policy_document.ejecucion_secretos.json
}

resource "aws_iam_role" "tarea" {
  name               = "${var.proyecto}-tarea"
  assume_role_policy = data.aws_iam_policy_document.tareas_ecs.json
}

data "aws_iam_policy_document" "tarea" {
  statement {
    sid       = "Archivos"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = ["${aws_s3_bucket.archivos.arn}/*"]
  }
  statement {
    sid = "EcsExec"
    actions = [
      "ssmmessages:CreateControlChannel",
      "ssmmessages:CreateDataChannel",
      "ssmmessages:OpenControlChannel",
      "ssmmessages:OpenDataChannel",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "tarea" {
  name   = "app"
  role   = aws_iam_role.tarea.id
  policy = data.aws_iam_policy_document.tarea.json
}
