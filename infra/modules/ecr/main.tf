locals {
  repos = {
    backend  = "${var.project_name}-backend"
    frontend = "${var.project_name}-frontend"
  }
}

resource "aws_ecr_repository" "this" {
  for_each             = local.repos
  name                 = each.value
  image_tag_mutability = "MUTABLE"
  force_delete         = true # demo posture: terraform destroy must not fail on lingering tagged images.

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  tags = { Name = each.value }
}

# Lifecycle: prune untagged images after 7 days; cap tagged images at 20 to
# keep storage cost predictable across rebuilds.
resource "aws_ecr_lifecycle_policy" "this" {
  for_each   = aws_ecr_repository.this
  repository = each.value.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Expire untagged images after 7 days"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = 7
        }
        action = { type = "expire" }
      },
      {
        rulePriority = 2
        description  = "Keep only the 20 most recent tagged images"
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = 20
        }
        action = { type = "expire" }
      }
    ]
  })
}
