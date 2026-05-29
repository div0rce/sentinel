# Postgres 16 single-AZ db.t4g.micro. Cost-minimal demo posture.
#
# Invariant: publicly_accessible = false. The DB is reachable only from the
# backend security group (the network module configures rds_sg with that
# ingress). The DB subnet group binds to the same public subnets the ECS tasks
# use because we have no private subnets in the no-NAT design — but the SG is
# what enforces "internal-only".
#
# pgvector ships in the Postgres engine via an extension. The migration created
# in M1 runs `CREATE EXTENSION IF NOT EXISTS vector` against the freshly
# provisioned DB. The parameter group does not need shared_preload_libraries
# for pgvector specifically (unlike e.g. pg_stat_statements); pgvector loads on
# CREATE EXTENSION.

resource "aws_db_subnet_group" "this" {
  name       = "${var.project_name}-db-subnets"
  subnet_ids = var.subnet_ids

  tags = { Name = "${var.project_name}-db-subnets" }
}

resource "aws_db_parameter_group" "this" {
  name   = "${var.project_name}-pg16"
  family = "postgres16"

  parameter {
    name  = "log_statement"
    value = "ddl" # log DDL only; demo posture, keeps log volume low.
  }

  tags = { Name = "${var.project_name}-pg16" }
}

resource "aws_db_instance" "this" {
  identifier        = "${var.project_name}-db"
  engine            = "postgres"
  engine_version    = "16.4"
  instance_class    = var.instance_class
  allocated_storage = var.allocated_storage
  storage_type      = "gp3"
  storage_encrypted = true

  db_name  = var.db_name
  username = var.db_username
  password = var.db_password
  port     = 5432

  vpc_security_group_ids = [var.ingress_sg_id]
  db_subnet_group_name   = aws_db_subnet_group.this.name
  parameter_group_name   = aws_db_parameter_group.this.name

  publicly_accessible = false # Hard invariant for the demo. Do not flip.
  multi_az            = false # Single-AZ for cost. Do not run production this way.
  skip_final_snapshot = true  # Demo posture: terraform destroy should be cheap.
  deletion_protection = false # Demo posture: same reason.
  apply_immediately   = true

  backup_retention_period      = 1
  performance_insights_enabled = false

  tags = { Name = "${var.project_name}-db" }
}
