data "aws_availability_zones" "disponibles" {
  state = "available"
}

resource "aws_vpc" "principal" {
  cidr_block           = local.cidr
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = { Name = var.proyecto }
}

resource "aws_default_security_group" "sin_reglas" {
  vpc_id = aws_vpc.principal.id
}

resource "aws_internet_gateway" "principal" {
  vpc_id = aws_vpc.principal.id
  tags   = { Name = var.proyecto }
}

resource "aws_subnet" "publica" {
  count             = length(local.zonas)
  vpc_id            = aws_vpc.principal.id
  availability_zone = local.zonas[count.index]
  cidr_block        = cidrsubnet(local.cidr, 8, count.index)
  tags              = { Name = "${var.proyecto}-publica-${local.zonas[count.index]}" }
}

resource "aws_subnet" "privada" {
  count             = length(local.zonas)
  vpc_id            = aws_vpc.principal.id
  availability_zone = local.zonas[count.index]
  cidr_block        = cidrsubnet(local.cidr, 8, 10 + count.index)
  tags              = { Name = "${var.proyecto}-privada-${local.zonas[count.index]}" }
}

resource "aws_route_table" "publica" {
  vpc_id = aws_vpc.principal.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.principal.id
  }
  tags = { Name = "${var.proyecto}-publica" }
}

resource "aws_route_table" "privada" {
  vpc_id = aws_vpc.principal.id
  tags   = { Name = "${var.proyecto}-privada" }
}

resource "aws_route_table_association" "publica" {
  count          = length(aws_subnet.publica)
  subnet_id      = aws_subnet.publica[count.index].id
  route_table_id = aws_route_table.publica.id
}

resource "aws_route_table_association" "privada" {
  count          = length(aws_subnet.privada)
  subnet_id      = aws_subnet.privada[count.index].id
  route_table_id = aws_route_table.privada.id
}
