variable "project_name" {
  type = string
}

variable "region" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "public_subnet_ids" {
  type = list(string)
}

variable "alb_sg_id" {
  type = string
}

variable "backend_sg_id" {
  type = string
}

variable "frontend_sg_id" {
  type = string
}

variable "backend_image" {
  description = "Full image URI including tag for the backend container."
  type        = string
}

variable "frontend_image" {
  description = "Full image URI including tag for the frontend container."
  type        = string
}

variable "backend_desired_count" {
  type    = number
  default = 1
}

variable "frontend_desired_count" {
  type    = number
  default = 1
}

variable "log_retention_days" {
  type    = number
  default = 7
}

variable "database_url_secret_arn" {
  type = string
}

variable "anthropic_key_secret_arn" {
  type = string
}

variable "openai_key_secret_arn" {
  type = string
}
