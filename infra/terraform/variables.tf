# Put real values in terraform.tfvars (gitignored), or export TF_VAR_<name>. Never commit secrets.

variable "github_repo" {
  description = "owner/name of the GitHub repository (connect GitHub to Render and Vercel first)"
  type        = string
}

variable "branch" {
  description = "Branch to deploy"
  type        = string
  default     = "main"
}

# --- provider credentials ---
variable "render_api_key" {
  type      = string
  sensitive = true
}

variable "render_owner_id" {
  description = "Render workspace id (usr-... or tea-...), from the dashboard URL or the API"
  type        = string
}

variable "neon_api_key" {
  type      = string
  sensitive = true
}

variable "neon_org_id" {
  description = "Neon organization id (org-...). Required for accounts that belong to an organization."
  type        = string
  default     = ""
}

variable "upstash_email" {
  type = string
}

variable "upstash_api_key" {
  type      = string
  sensitive = true
}

variable "vercel_api_token" {
  type      = string
  sensitive = true
}

variable "vercel_team" {
  description = "Vercel team slug or id; leave empty for a personal account"
  type        = string
  default     = null
}

# --- application settings ---
variable "gemini_api_key" {
  type      = string
  sensitive = true
}

variable "gemini_model" {
  description = "Fast model id, e.g. a current Gemini Flash model from aistudio.google.com"
  type        = string
}

variable "gemini_strong_model" {
  description = "Stronger model for decisions; empty uses gemini_model"
  type        = string
  default     = ""
}

variable "daily_ai_calls" {
  description = "Hard cap on real-model calls per day; the offline assistant answers after it"
  type        = number
  default     = 150
}

variable "model_price_per_1k_tokens" {
  description = "Blended USD price per 1k tokens, for the cost-per-conversation metric"
  type        = string
  default     = ""
}

variable "demo_staff_login" {
  description = "true lets any visitor try the staff roles (a public portfolio demo). false requires staff_access_code."
  type        = bool
  default     = true
}

variable "staff_access_code" {
  type      = string
  sensitive = true
  default   = ""
}

variable "stripe_secret_key" {
  description = "Stripe TEST key (sk_test_...). Live keys are refused by the app."
  type        = string
  sensitive   = true
  default     = ""
}

variable "stripe_webhook_secret" {
  type      = string
  sensitive = true
  default   = ""
}

variable "otel_endpoint" {
  description = "Grafana Cloud OTLP endpoint, e.g. https://otlp-gateway-prod-us-west-0.grafana.net/otlp"
  type        = string
  default     = ""
}

variable "otel_headers" {
  description = "OTLP auth header, e.g. Authorization=Basic <base64 instance-id:token>"
  type        = string
  sensitive   = true
  default     = ""
}

variable "langsmith_api_key" {
  type      = string
  sensitive = true
  default   = ""
}
