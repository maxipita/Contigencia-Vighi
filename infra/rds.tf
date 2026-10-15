resource "random_password" "base" {
  length  = 32
  special = false
}

resource "aws_db_subnet_group" "principal" {
  name       = var.proyecto
  subnet_ids = aws_subnet.privada[*].id
}

resource "aws_db_instance" "principal" {
  identifier                 = var.proyecto
  engine                     = "postgres"
  engine_version             = "17"
  instance_class             = var.rds_clase
  allocated_storage          = 20
  max_allocated_storage      = 100
  storage_type               = "gp3"
  storage_encrypted          = true
  db_name                    = "vighi"
  username                   = "vighi"
  password                   = random_password.base.result
  db_subnet_group_name       = aws_db_subnet_group.principal.name
  vpc_security_group_ids     = [aws_security_group.rds.id]
  publicly_accessible        = false
  multi_az                   = false
  backup_retention_period    = 7
  backup_window              = "06:00-06:30"
  maintenance_window         = "sun:06:45-sun:07:45"
  auto_minor_version_upgrade = true
  copy_tags_to_snapshot      = true
  deletion_protection        = true
  skip_final_snapshot        = false
  final_snapshot_identifier  = "${var.proyecto}-final"
}
