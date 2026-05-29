variable "project_name" {
  type = string
}

variable "github_repository" {
  description = "owner/name. Trust policy is scoped to repo:OWNER/NAME:* (any branch, ref, env)."
  type        = string
  validation {
    condition     = can(regex("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", var.github_repository))
    error_message = "github_repository must be in 'owner/name' form."
  }
}

variable "ecr_repository_arns" {
  type = list(string)
}

variable "ecs_cluster_arn" {
  type = string
}

variable "ecs_service_arns" {
  type = list(string)
}
