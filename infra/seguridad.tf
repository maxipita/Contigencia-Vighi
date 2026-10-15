resource "aws_security_group" "alb" {
  name        = "${var.proyecto}-alb"
  description = "Entrada publica HTTP/HTTPS al balanceador"
  vpc_id      = aws_vpc.principal.id
}

resource "aws_security_group" "app" {
  name        = "${var.proyecto}-app"
  description = "Tareas ECS: solo reciben trafico del balanceador"
  vpc_id      = aws_vpc.principal.id
}

resource "aws_security_group" "rds" {
  name        = "${var.proyecto}-rds"
  description = "PostgreSQL: solo desde las tareas ECS"
  vpc_id      = aws_vpc.principal.id
}

resource "aws_vpc_security_group_ingress_rule" "alb_http" {
  security_group_id = aws_security_group.alb.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 80
  to_port           = 80
}

resource "aws_vpc_security_group_ingress_rule" "alb_https" {
  security_group_id = aws_security_group.alb.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}

resource "aws_vpc_security_group_egress_rule" "alb_a_app" {
  security_group_id            = aws_security_group.alb.id
  referenced_security_group_id = aws_security_group.app.id
  ip_protocol                  = "tcp"
  from_port                    = 8080
  to_port                      = 8080
}

resource "aws_vpc_security_group_ingress_rule" "app_desde_alb" {
  security_group_id            = aws_security_group.app.id
  referenced_security_group_id = aws_security_group.alb.id
  ip_protocol                  = "tcp"
  from_port                    = 8080
  to_port                      = 8080
}

resource "aws_vpc_security_group_egress_rule" "app_salida" {
  security_group_id = aws_security_group.app.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
}

resource "aws_vpc_security_group_ingress_rule" "rds_desde_app" {
  security_group_id            = aws_security_group.rds.id
  referenced_security_group_id = aws_security_group.app.id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
}
