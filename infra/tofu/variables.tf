variable "region" {
  description = "AWS region for all resources."
  type        = string
  default     = "us-east-1"
}

variable "project" {
  description = "Name prefix for all resources."
  type        = string
  default     = "agenticu"
}

variable "container_image" {
  description = "ECR image for the AgentICU API (after docker push). E.g. 123456789012.dkr.ecr.us-east-1.amazonaws.com/agenticu:latest"
  type        = string
}

variable "db_instance_class" {
  description = "RDS instance class (keep small to control cost)."
  type        = string
  default     = "db.t4g.micro"
}

variable "db_allocated_storage" {
  description = "RDS storage in GB."
  type        = number
  default     = 20
}

variable "desired_count" {
  description = "ECS desired task count per service."
  type        = number
  default     = 1
}

variable "api_key" {
  description = "AgentICU API key (empty = no auth, like local dev)."
  type        = string
  default     = ""
  sensitive   = true
}

variable "grafana_image" {
  description = "Grafana container image."
  type        = string
  default     = "grafana/grafana:latest"
}
