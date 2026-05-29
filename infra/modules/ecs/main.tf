# ECS cluster, ALB, and two Fargate task definitions. The frontend serves the
# SPA over nginx on port 8080 and reverse-proxies /api/* to the backend service
# via service discovery. The ALB default target is the frontend so /, /review,
# and /dashboard all serve the React SPA. Only backend health checks bypass
# nginx and route straight to FastAPI.

# --- log groups ---------------------------------------------------------------

resource "aws_cloudwatch_log_group" "backend" {
  name              = "/ecs/${var.project_name}-backend"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "frontend" {
  name              = "/ecs/${var.project_name}-frontend"
  retention_in_days = var.log_retention_days
}

# --- IAM ----------------------------------------------------------------------
#
# Two roles per ECS task:
#   - execution role: pulls the image from ECR, writes to CloudWatch Logs, and
#     reads the SSM SecureString parameters at task start.
#   - task role:     the application's runtime identity. The backend uses it
#     for nothing today (the LLM/embeddings keys come in via secrets, not via
#     a role); the role exists so we can attach policies cleanly when an M11+
#     feature needs them.

data "aws_iam_policy_document" "ecs_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "task_execution" {
  name               = "${var.project_name}-task-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy_attachment" "task_execution_managed" {
  role       = aws_iam_role.task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# Allow the execution role to read the SecureString parameters that back the
# task definition's `secrets` block. Scoped tightly to our parameter ARNs.
data "aws_iam_policy_document" "task_execution_secrets" {
  statement {
    actions = [
      "ssm:GetParameter",
      "ssm:GetParameters",
    ]
    resources = [
      var.database_url_secret_arn,
      var.anthropic_key_secret_arn,
      var.openai_key_secret_arn,
    ]
  }
  statement {
    actions   = ["kms:Decrypt"]
    resources = ["*"] # SSM SecureString uses the AWS-managed alias/aws/ssm key.
    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["ssm.${var.region}.amazonaws.com"]
    }
  }
}

resource "aws_iam_policy" "task_execution_secrets" {
  name   = "${var.project_name}-task-execution-secrets"
  policy = data.aws_iam_policy_document.task_execution_secrets.json
}

resource "aws_iam_role_policy_attachment" "task_execution_secrets" {
  role       = aws_iam_role.task_execution.name
  policy_arn = aws_iam_policy.task_execution_secrets.arn
}

resource "aws_iam_role" "task_app" {
  name               = "${var.project_name}-task-app"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

# --- cluster ------------------------------------------------------------------

resource "aws_ecs_cluster" "this" {
  name = "${var.project_name}-cluster"

  setting {
    name  = "containerInsights"
    value = "disabled" # cost posture; flip to enabled when there's a bill to justify it.
  }
}

# --- ALB ----------------------------------------------------------------------

resource "aws_lb" "this" {
  name               = "${var.project_name}-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [var.alb_sg_id]
  subnets            = var.public_subnet_ids
  idle_timeout       = 60
}

resource "aws_lb_target_group" "frontend" {
  name        = "${var.project_name}-frontend"
  port        = 8080
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"

  health_check {
    path                = "/"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    interval            = 15
    timeout             = 5
    matcher             = "200-399"
  }
}

resource "aws_lb_target_group" "backend" {
  name        = "${var.project_name}-backend"
  port        = 8000
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"

  health_check {
    path                = "/health"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    interval            = 15
    timeout             = 5
    matcher             = "200"
  }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.this.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.frontend.arn
  }
}

# Backend health checks stay backend-specific. API calls use the ALB default
# frontend target and are proxied by nginx under /api/*, which lets nginx strip
# the deployment namespace before FastAPI sees the request path.
resource "aws_lb_listener_rule" "backend" {
  listener_arn = aws_lb_listener.http.arn
  priority     = 100

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.backend.arn
  }

  condition {
    path_pattern {
      values = ["/health"]
    }
  }
}

# --- service discovery (private namespace, used by nginx → backend) ----------

resource "aws_service_discovery_private_dns_namespace" "this" {
  name = "${var.project_name}.local"
  vpc  = var.vpc_id
}

resource "aws_service_discovery_service" "backend" {
  name = "backend"

  dns_config {
    namespace_id   = aws_service_discovery_private_dns_namespace.this.id
    routing_policy = "MULTIVALUE"

    dns_records {
      ttl  = 10
      type = "A"
    }
  }

  health_check_custom_config {
    failure_threshold = 1
  }
}

# --- task definitions ---------------------------------------------------------

locals {
  backend_container = jsonencode([
    {
      name      = "backend"
      image     = var.backend_image
      essential = true
      portMappings = [
        { containerPort = 8000, protocol = "tcp" }
      ]
      environment = [
        { name = "PORT", value = "8000" },
        { name = "EMBEDDINGS_PROVIDER", value = "openai" },
        { name = "LLM_PROVIDER", value = "anthropic" },
        { name = "EMBEDDING_DIM", value = "1536" },
        { name = "OPENAI_EMBEDDING_MODEL", value = "text-embedding-3-small" },
        { name = "CLAUDE_MODEL", value = "claude-sonnet-4-6" },
        { name = "LLM_TEMPERATURE", value = "0.0" },
        { name = "PII_REDACTION_ENABLED", value = "true" },
        { name = "SENTINEL_LOG_FORMAT", value = "json" },
      ]
      secrets = [
        { name = "DATABASE_URL", valueFrom = var.database_url_secret_arn },
        { name = "ANTHROPIC_API_KEY", valueFrom = var.anthropic_key_secret_arn },
        { name = "OPENAI_API_KEY", valueFrom = var.openai_key_secret_arn },
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.backend.name
          awslogs-region        = var.region
          awslogs-stream-prefix = "ecs"
        }
      }
    }
  ])

  frontend_container = jsonencode([
    {
      name      = "frontend"
      image     = var.frontend_image
      essential = true
      portMappings = [
        { containerPort = 8080, protocol = "tcp" }
      ]
      environment = [
        # The nginx config template substitutes ${BACKEND_URL} on container
        # start. Service discovery resolves backend.<project>.local in-VPC.
        { name = "BACKEND_URL", value = "http://backend.${var.project_name}.local:8000" },
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.frontend.name
          awslogs-region        = var.region
          awslogs-stream-prefix = "ecs"
        }
      }
    }
  ])
}

resource "aws_ecs_task_definition" "backend" {
  family                   = "${var.project_name}-backend"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "256"
  memory                   = "512"
  execution_role_arn       = aws_iam_role.task_execution.arn
  task_role_arn            = aws_iam_role.task_app.arn
  container_definitions    = local.backend_container
}

resource "aws_ecs_task_definition" "frontend" {
  family                   = "${var.project_name}-frontend"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "256"
  memory                   = "512"
  execution_role_arn       = aws_iam_role.task_execution.arn
  task_role_arn            = aws_iam_role.task_app.arn
  container_definitions    = local.frontend_container
}

# --- services -----------------------------------------------------------------

resource "aws_ecs_service" "backend" {
  name            = "${var.project_name}-backend"
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.backend.arn
  desired_count   = var.backend_desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.public_subnet_ids
    security_groups  = [var.backend_sg_id]
    assign_public_ip = true # Required in no-NAT topology so tasks can reach ECR/Anthropic/OpenAI.
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.backend.arn
    container_name   = "backend"
    container_port   = 8000
  }

  service_registries {
    registry_arn = aws_service_discovery_service.backend.arn
  }

  deployment_minimum_healthy_percent = 50
  deployment_maximum_percent         = 200
  enable_execute_command             = false

  depends_on = [aws_lb_listener.http]
}

resource "aws_ecs_service" "frontend" {
  name            = "${var.project_name}-frontend"
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.frontend.arn
  desired_count   = var.frontend_desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.public_subnet_ids
    security_groups  = [var.frontend_sg_id]
    assign_public_ip = true
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.frontend.arn
    container_name   = "frontend"
    container_port   = 8080
  }

  deployment_minimum_healthy_percent = 50
  deployment_maximum_percent         = 200

  depends_on = [aws_lb_listener.http]
}
