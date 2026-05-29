# Public-subnet/no-NAT VPC. Cost posture: avoids the ~$32/month idle NAT Gateway.
# Demo-only — RDS still binds to a private security group so it is not reachable
# from the internet.

resource "aws_vpc" "this" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = { Name = "${var.project_name}-vpc" }
}

resource "aws_internet_gateway" "this" {
  vpc_id = aws_vpc.this.id
  tags   = { Name = "${var.project_name}-igw" }
}

resource "aws_subnet" "public" {
  count                   = length(var.public_subnet_cidrs)
  vpc_id                  = aws_vpc.this.id
  cidr_block              = var.public_subnet_cidrs[count.index]
  availability_zone       = var.availability_zones[count.index]
  map_public_ip_on_launch = true

  tags = {
    Name = "${var.project_name}-public-${var.availability_zones[count.index]}"
    Tier = "public"
  }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.this.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.this.id
  }

  tags = { Name = "${var.project_name}-public-rt" }
}

resource "aws_route_table_association" "public" {
  count          = length(aws_subnet.public)
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

# --- security groups -----------------------------------------------------------
#
# SGs live here (not in ecs/rds) so the rds ingress rule can reference the
# backend SG without creating an ecs → rds → ecs module-level cycle. The four
# SGs encode the expected reachability graph:
#
#   internet ──→ alb_sg (80, 443)
#   alb_sg   ──→ frontend_sg (80)         (ALB to nginx)
#   alb_sg   ──→ backend_sg  (8000)       (ALB to FastAPI for path-prefix routes)
#   backend_sg ──→ rds_sg    (5432)       (FastAPI to Postgres)
#
# Egress is intentionally open: tasks need to reach ECR, Anthropic, OpenAI, and
# CloudWatch Logs. RDS does not need egress.

resource "aws_security_group" "alb" {
  name        = "${var.project_name}-alb"
  description = "Public-facing ALB."
  vpc_id      = aws_vpc.this.id

  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    description = "HTTP from anywhere."
  }

  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    description = "HTTPS from anywhere (used when a TLS cert is attached; no listener wired by default)."
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${var.project_name}-alb" }
}

resource "aws_security_group" "frontend" {
  name        = "${var.project_name}-frontend"
  description = "Frontend Fargate task. Reachable from the ALB only."
  vpc_id      = aws_vpc.this.id

  ingress {
    from_port       = 80
    to_port         = 80
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
    description     = "ALB → nginx."
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${var.project_name}-frontend" }
}

resource "aws_security_group" "backend" {
  name        = "${var.project_name}-backend"
  description = "Backend Fargate task. Reachable from the ALB only."
  vpc_id      = aws_vpc.this.id

  ingress {
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
    description     = "ALB → FastAPI."
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${var.project_name}-backend" }
}

resource "aws_security_group" "rds" {
  name        = "${var.project_name}-rds"
  description = "Postgres. Reachable from the backend task only. Not publicly accessible."
  vpc_id      = aws_vpc.this.id

  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.backend.id]
    description     = "Backend → Postgres."
  }

  # No egress — Postgres does not need to reach out.

  tags = { Name = "${var.project_name}-rds" }
}
