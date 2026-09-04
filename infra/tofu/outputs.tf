output "api_url" {
  description = "AgentICU API base URL (point the TUI here)."
  value       = "http://${aws_lb.main.dns_name}"
}

output "grafana_url" {
  description = "Grafana dashboard URL."
  value       = "http://${aws_lb.main.dns_name}:8080"
}

output "rds_endpoint" {
  description = "RDS Postgres endpoint."
  value       = aws_db_instance.db.address
}

output "ecr_repository" {
  description = "Push the Dockerfile image here before first apply."
  value       = aws_ecr_repository.api.repository_url
}
