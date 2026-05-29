output "role_arn" {
  description = "ARN of the GitHub Actions OIDC role. Add to the repo's AWS_ROLE_ARN secret."
  value       = aws_iam_role.ci.arn
}
