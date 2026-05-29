output "anthropic_key_arn" {
  value = aws_ssm_parameter.anthropic_api_key.arn
}

output "openai_key_arn" {
  value = aws_ssm_parameter.openai_api_key.arn
}

output "database_url_arn" {
  value = aws_ssm_parameter.database_url.arn
}
