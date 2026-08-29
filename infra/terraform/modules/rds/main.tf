/**
 * PostgreSQL 16 with pgvector.
 *
 * The settings that matter here are the recovery ones. docs/08 §8 sets
 * RPO <= 5 minutes and RTO <= 1 hour, and PITR is what delivers the RPO —
 * a nightly snapshot alone would put the RPO at 24 hours.
 */

variable "name" { type = string }
variable "vpc_id" { type = string }
variable "subnet_ids" { type = list(string) }
variable "instance_class" {
  type    = string
  default = "db.t4g.medium"
}
variable "multi_az" {
  type    = bool
  default = true
}
variable "allowed_security_group_ids" { type = list(string) }

resource "aws_db_subnet_group" "this" {
  name       = var.name
  subnet_ids = var.subnet_ids
}

resource "aws_security_group" "this" {
  name   = "${var.name}-db"
  vpc_id = var.vpc_id
}

# By security-group id, never by CIDR. A CIDR rule grants access to anything
# that happens to land in that subnet later.
resource "aws_vpc_security_group_ingress_rule" "postgres" {
  count                        = length(var.allowed_security_group_ids)
  security_group_id            = aws_security_group.this.id
  referenced_security_group_id = var.allowed_security_group_ids[count.index]
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
}

resource "aws_db_parameter_group" "this" {
  name   = var.name
  family = "postgres16"

  # pgvector and pgcrypto are created by migration 0001; the extension has to be
  # on the shared preload allow-list before that migration can run.
  parameter {
    name         = "shared_preload_libraries"
    value        = "pg_stat_statements"
    apply_method = "pending-reboot"
  }

  # Log anything slower than a second. Below that the log volume costs more than
  # the information is worth; above it, a slow query on a child's skill map is
  # something an on-call engineer needs to see.
  parameter {
    name  = "log_min_duration_statement"
    value = "1000"
  }
}

resource "aws_db_instance" "this" {
  identifier     = var.name
  engine         = "postgres"
  engine_version = "16"
  instance_class = var.instance_class

  allocated_storage     = 50
  max_allocated_storage = 500
  storage_encrypted     = true
  storage_type          = "gp3"

  db_subnet_group_name   = aws_db_subnet_group.this.name
  vpc_security_group_ids = [aws_security_group.this.id]
  parameter_group_name   = aws_db_parameter_group.this.name
  multi_az               = var.multi_az
  publicly_accessible    = false

  # docs/08 §8: 7-day PITR. `backup_retention_period > 0` is what enables
  # continuous WAL archiving, which is the RPO mechanism.
  backup_retention_period      = 7
  backup_window                = "01:00-02:00"
  maintenance_window           = "sun:03:00-sun:04:00"
  copy_tags_to_snapshot        = true
  performance_insights_enabled = true

  # A production database is never destroyed by a plan. Deleting one is a
  # deliberate, manual, logged act.
  deletion_protection       = true
  skip_final_snapshot       = false
  final_snapshot_identifier = "${var.name}-final"

  enabled_cloudwatch_logs_exports = ["postgresql", "upgrade"]

  lifecycle {
    ignore_changes = [engine_version]
  }
}

output "endpoint" { value = aws_db_instance.this.endpoint }
output "security_group_id" { value = aws_security_group.this.id }
