# GitHub Actions OIDC role for the manual-dispatch CD workflow.
#
# What it lets CI do (only):
#   - get an ECR auth token
#   - push images to the two project ECR repos
#   - update the two ECS services (force a redeployment with a new image tag)
#
# What it does NOT let CI do:
#   - create new IAM roles/policies
#   - touch RDS, secrets, the ALB, or the network
#   - read/write S3, run Lambda, anything outside ECR + ECS
#
# Trust policy is scoped to one repo (var.github_repository). Bumping it requires
# changing infra explicitly — no surprise repo can assume this role.

data "aws_caller_identity" "current" {}

# Reuse a single account-level OIDC provider for token.actions.githubusercontent.com.
# If one already exists, import it before applying.
resource "aws_iam_openid_connect_provider" "github" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"] # GitHub Actions root CA, current as of 2025/2026.
}

data "aws_iam_policy_document" "ci_assume" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repository}:*"]
    }
  }
}

resource "aws_iam_role" "ci" {
  name               = "${var.project_name}-ci"
  assume_role_policy = data.aws_iam_policy_document.ci_assume.json
}

data "aws_iam_policy_document" "ci_permissions" {
  # ECR auth (account-level) + push to the two project repos only.
  statement {
    sid       = "EcrAuth"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }
  statement {
    sid = "EcrPush"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:CompleteLayerUpload",
      "ecr:InitiateLayerUpload",
      "ecr:PutImage",
      "ecr:UploadLayerPart",
      "ecr:DescribeRepositories",
      "ecr:DescribeImages",
    ]
    resources = var.ecr_repository_arns
  }

  # ECS: force a new deployment on the two project services in this cluster.
  statement {
    sid       = "EcsDescribe"
    actions   = ["ecs:DescribeServices", "ecs:DescribeTasks", "ecs:ListTasks"]
    resources = ["*"]
  }
  statement {
    sid = "EcsUpdate"
    actions = [
      "ecs:UpdateService",
      "ecs:DescribeTaskDefinition",
      "ecs:RegisterTaskDefinition",
    ]
    resources = concat([var.ecs_cluster_arn], var.ecs_service_arns)
  }
  statement {
    # RegisterTaskDefinition expects an unscoped resource; allow it but the only
    # role this CI principal can pass is the task-execution / task-app role,
    # which is implicit (CD will reuse the existing definition's role ARNs).
    sid       = "EcsPassRole"
    actions   = ["iam:PassRole"]
    resources = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${var.project_name}-task-*"]
    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_policy" "ci" {
  name   = "${var.project_name}-ci"
  policy = data.aws_iam_policy_document.ci_permissions.json
}

resource "aws_iam_role_policy_attachment" "ci" {
  role       = aws_iam_role.ci.name
  policy_arn = aws_iam_policy.ci.arn
}
