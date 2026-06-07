# SSM Parameter Store entries for runtime secrets the ECS task pulls in via the
# task execution role.
#
# - anthropic/openai/gemini keys are placeholders. Overwrite out-of-band:
#       aws ssm put-parameter --name /sentinel/anthropic_api_key \
#         --type SecureString --value "$ANTHROPIC_API_KEY" --overwrite
#   `lifecycle.ignore_changes = [value]` keeps Terraform from clobbering the
#   real value on subsequent applies. The gemini key is provisioned by default
#   but only consumed when a provider is set to "gemini".
#
# - DATABASE_URL is composed from RDS outputs supplied by the caller. It is
#   sensitive (carries the master password) but Terraform-owned, so its
#   `value` *is* tracked.

locals {
  prefix = "/${var.project_name}"
  database_url = format(
    "postgresql+psycopg://%s:%s@%s/%s",
    var.db_username,
    var.db_password,
    var.db_endpoint,
    var.db_name,
  )
}

resource "aws_ssm_parameter" "anthropic_api_key" {
  name        = "${local.prefix}/anthropic_api_key"
  description = "Anthropic API key consumed by the backend at task start. Overwrite out-of-band."
  type        = "SecureString"
  value       = "REPLACE_ME"

  lifecycle {
    ignore_changes = [value]
  }
}

resource "aws_ssm_parameter" "openai_api_key" {
  name        = "${local.prefix}/openai_api_key"
  description = "OpenAI API key consumed by the backend at task start. Overwrite out-of-band."
  type        = "SecureString"
  value       = "REPLACE_ME"

  lifecycle {
    ignore_changes = [value]
  }
}

# Provisioned by default but only consumed when llm_provider or embeddings_provider
# is set to "gemini". Overwrite out-of-band like the other keys.
resource "aws_ssm_parameter" "gemini_api_key" {
  name        = "${local.prefix}/gemini_api_key"
  description = "Gemini API key consumed by the backend at task start. Overwrite out-of-band."
  type        = "SecureString"
  value       = "REPLACE_ME"

  lifecycle {
    ignore_changes = [value]
  }
}

resource "aws_ssm_parameter" "database_url" {
  name        = "${local.prefix}/database_url"
  description = "psycopg URL for the RDS instance. Composed from rds outputs."
  type        = "SecureString"
  value       = local.database_url
}
