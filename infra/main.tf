data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  common_tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
    Repository  = var.github_repository
  }

  # Pick the first two AZs in the region. Single-AZ RDS uses the first only.
  azs = slice(data.aws_availability_zones.available.names, 0, 2)
}

module "network" {
  source = "./modules/network"

  project_name        = var.project_name
  vpc_cidr            = var.vpc_cidr
  public_subnet_cidrs = var.public_subnet_cidrs
  availability_zones  = local.azs
}

module "ecr" {
  source = "./modules/ecr"

  project_name = var.project_name
}

# RDS depends on the backend security group from the network module so its
# ingress can be scoped to that SG only (RDS is not publicly accessible).
module "rds" {
  source = "./modules/rds"

  project_name      = var.project_name
  vpc_id            = module.network.vpc_id
  subnet_ids        = module.network.public_subnet_ids
  ingress_sg_id     = module.network.backend_sg_id
  db_name           = var.db_name
  db_username       = var.db_username
  db_password       = var.db_password
  instance_class    = var.db_instance_class
  allocated_storage = var.db_allocated_storage
}

# Secrets module composes the DATABASE_URL from rds outputs and owns the API key
# parameters. ECS depends on its outputs.
module "secrets" {
  source = "./modules/secrets"

  project_name = var.project_name
  db_endpoint  = module.rds.db_endpoint
  db_name      = var.db_name
  db_username  = var.db_username
  db_password  = var.db_password
}

module "ecs" {
  source = "./modules/ecs"

  project_name           = var.project_name
  region                 = var.region
  vpc_id                 = module.network.vpc_id
  public_subnet_ids      = module.network.public_subnet_ids
  alb_sg_id              = module.network.alb_sg_id
  backend_sg_id          = module.network.backend_sg_id
  frontend_sg_id         = module.network.frontend_sg_id
  backend_image          = "${module.ecr.backend_repository_url}:${var.backend_image_tag}"
  frontend_image         = "${module.ecr.frontend_repository_url}:${var.frontend_image_tag}"
  backend_desired_count  = var.backend_desired_count
  frontend_desired_count = var.frontend_desired_count
  log_retention_days     = var.log_retention_days

  database_url_secret_arn  = module.secrets.database_url_arn
  anthropic_key_secret_arn = module.secrets.anthropic_key_arn
  openai_key_secret_arn    = module.secrets.openai_key_arn
}

# OIDC role for the GitHub Actions CD workflow. Created only when a repo is supplied.
module "ci_oidc" {
  source = "./modules/ci_oidc"
  count  = var.github_repository == "" ? 0 : 1

  project_name        = var.project_name
  github_repository   = var.github_repository
  ecr_repository_arns = [module.ecr.backend_repository_arn, module.ecr.frontend_repository_arn]
  ecs_cluster_arn     = module.ecs.cluster_arn
  ecs_service_arns    = [module.ecs.backend_service_arn, module.ecs.frontend_service_arn]
}
