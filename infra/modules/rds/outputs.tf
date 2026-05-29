output "db_endpoint" {
  description = "host:port form, ready to drop into a postgres URL."
  value       = aws_db_instance.this.endpoint
}

output "db_address" {
  value = aws_db_instance.this.address
}
