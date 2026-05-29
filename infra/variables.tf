variable "project_name" {
  description = "Short name used as a prefix on every resource."
  type        = string
  default     = "sentinel"
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,30}$", var.project_name))
    error_message = "project_name must be lowercase, start with a letter, and use only [a-z0-9-]."
  }
}

variable "environment" {
  description = "Environment label (free-form). Tags only; not used in resource names."
  type        = string
  default     = "demo"
}

variable "region" {
  description = "AWS region."
  type        = string
  default     = "us-east-1"
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC."
  type        = string
  default     = "10.0.0.0/16"
}

variable "public_subnet_cidrs" {
  description = "Two /24 CIDRs for the public subnets in two AZs."
  type        = list(string)
  default     = ["10.0.0.0/24", "10.0.1.0/24"]
  validation {
    condition     = length(var.public_subnet_cidrs) == 2
    error_message = "Exactly two subnet CIDRs are required (one per AZ)."
  }
}

variable "db_username" {
  description = "Postgres master username."
  type        = string
  default     = "sentinel"
}

variable "db_password" {
  description = <<-EOD
    Postgres master password. Required at apply time. Pass via TF_VAR_db_password
    (preferred) or a -var '...' flag — never commit. Min 16 chars.
  EOD
  type        = string
  sensitive   = true
  validation {
    condition     = length(var.db_password) >= 16
    error_message = "db_password must be at least 16 characters."
  }
}

variable "db_name" {
  description = "Initial Postgres database name."
  type        = string
  default     = "sentinel"
}

variable "db_instance_class" {
  description = "RDS instance class. Cost-minimal default; do not run production on db.t4g.micro."
  type        = string
  default     = "db.t4g.micro"
}

variable "db_allocated_storage" {
  description = "RDS storage in GB. 20 is the floor on db.t4g.micro and is enough for the demo corpus."
  type        = number
  default     = 20
}

variable "backend_image_tag" {
  description = "ECR image tag for the backend service. CD overrides this with the git SHA."
  type        = string
  default     = "latest"
}

variable "frontend_image_tag" {
  description = "ECR image tag for the frontend service. CD overrides this with the git SHA."
  type        = string
  default     = "latest"
}

variable "backend_desired_count" {
  description = "ECS service desired task count for the backend."
  type        = number
  default     = 1
}

variable "frontend_desired_count" {
  description = "ECS service desired task count for the frontend."
  type        = number
  default     = 1
}

variable "github_repository" {
  description = <<-EOD
    GitHub repo in 'owner/name' form. Used to scope the OIDC trust policy on the
    CI deploy role so only this repo can assume it. Empty disables the OIDC role.
  EOD
  type        = string
  default     = ""
}

variable "log_retention_days" {
  description = "CloudWatch Logs retention for the ECS task log groups."
  type        = number
  default     = 7
}
