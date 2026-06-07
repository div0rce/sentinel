variable "project_name" {
  type = string
}

variable "region" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "public_subnet_ids" {
  type = list(string)
}

variable "alb_sg_id" {
  type = string
}

variable "backend_sg_id" {
  type = string
}

variable "frontend_sg_id" {
  type = string
}

variable "backend_image" {
  description = "Full image URI including tag for the backend container."
  type        = string
}

variable "frontend_image" {
  description = "Full image URI including tag for the frontend container."
  type        = string
}

variable "backend_desired_count" {
  type    = number
  default = 1
}

variable "frontend_desired_count" {
  type    = number
  default = 1
}

variable "log_retention_days" {
  type    = number
  default = 7
}

variable "database_url_secret_arn" {
  type = string
}

variable "anthropic_key_secret_arn" {
  type = string
}

variable "openai_key_secret_arn" {
  type = string
}

variable "gemini_key_secret_arn" {
  description = "ARN of the SSM SecureString containing the Gemini API key."
  type        = string
}

# --- backend provider selection (env-driven; defaults preserve today's behaviour) ---

variable "llm_provider" {
  description = "Backend LLM provider."
  type        = string
  default     = "anthropic"

  validation {
    condition     = contains(["anthropic", "gemini", "fake"], var.llm_provider)
    error_message = "llm_provider must be one of: anthropic, gemini, fake."
  }
}

variable "embeddings_provider" {
  description = "Backend embeddings provider."
  type        = string
  default     = "openai"

  validation {
    condition     = contains(["openai", "voyage", "gemini", "fake"], var.embeddings_provider)
    error_message = "embeddings_provider must be one of: openai, voyage, gemini, fake."
  }
}

variable "embedding_dim" {
  description = "Embedding vector dimensionality. Must match the pgvector schema (1536)."
  type        = string
  default     = "1536"
}

variable "claude_model" {
  description = "Anthropic model id (used when llm_provider = anthropic)."
  type        = string
  default     = "claude-sonnet-4-6"
}

variable "openai_embedding_model" {
  description = "OpenAI embedding model id (used when embeddings_provider = openai)."
  type        = string
  default     = "text-embedding-3-small"
}

variable "gemini_model" {
  description = "Gemini chat model id (used when llm_provider = gemini)."
  type        = string
  default     = "gemini-3.5-flash"
}

variable "gemini_embedding_model" {
  description = "Gemini embedding model id (used when embeddings_provider = gemini)."
  type        = string
  default     = "gemini-embedding-2"
}
