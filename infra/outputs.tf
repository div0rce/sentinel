output "alb_dns_name" {
  description = "Public DNS name of the Application Load Balancer. Visit http://{this} once tasks are healthy."
  value       = module.ecs.alb_dns_name
}

output "ecr_backend_repository_url" {
  description = "ECR repository URL for the backend image. CD pushes here."
  value       = module.ecr.backend_repository_url
}

output "ecr_frontend_repository_url" {
  description = "ECR repository URL for the frontend image. CD pushes here."
  value       = module.ecr.frontend_repository_url
}

output "ecs_cluster_name" {
  description = "ECS cluster name (used by CD when forcing service deployments)."
  value       = module.ecs.cluster_name
}

output "ecs_backend_service_name" {
  description = "ECS backend service name."
  value       = module.ecs.backend_service_name
}

output "ecs_frontend_service_name" {
  description = "ECS frontend service name."
  value       = module.ecs.frontend_service_name
}

output "rds_endpoint" {
  description = "Postgres endpoint (host:port). Not publicly reachable; used by ECS tasks only."
  value       = module.rds.db_endpoint
}

output "ci_role_arn" {
  description = "ARN of the GitHub-Actions OIDC role, if created. Add this to the repo's AWS_ROLE_ARN secret."
  value       = try(module.ci_oidc[0].role_arn, null)
}
