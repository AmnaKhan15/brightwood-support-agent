# Brightwood Support Agent: the whole free-tier stack as code.
#
#   Neon     Postgres + pgvector  (sandboxes, run log, help vectors, LangGraph checkpoints)
#   Upstash  Redis                (sandbox registry, rate limits, AI budget, job queue)
#   Render   the Python API       (Docker, built from this repo's Dockerfile, with an embedded job worker)
#   Vercel   the Next.js site     (web/, proxies /api/* to the Render service)
#
# Grafana Cloud (OpenTelemetry) and LangSmith are configured by passing their endpoint and keys as variables;
# they need no resources here. Regions are matched (Oregon / us-west-2) so the API is close to its data.

provider "render" {
  api_key  = var.render_api_key
  owner_id = var.render_owner_id
}

provider "neon" {
  api_key = var.neon_api_key
}

provider "upstash" {
  email   = var.upstash_email
  api_key = var.upstash_api_key
}

provider "vercel" {
  api_token = var.vercel_api_token
  team      = var.vercel_team
}

locals {
  repo_url  = "https://github.com/${var.github_repo}"
  redis_url = "rediss://default:${upstash_redis_database.cache.password}@${upstash_redis_database.cache.endpoint}:${upstash_redis_database.cache.port}"

  # Settings every deploy needs, plus optional ones only when they are given.
  api_env = merge(
    {
      DATABASE_URL     = { value = neon_project.db.connection_uri }
      REDIS_URL        = { value = local.redis_url }
      GEMINI_API_KEY   = { value = var.gemini_api_key }
      GEMINI_MODEL     = { value = var.gemini_model }
      DAILY_AI_CALLS   = { value = tostring(var.daily_ai_calls) }
      DEMO_STAFF_LOGIN = { value = tostring(var.demo_staff_login) }
      EMBEDDED_WORKER  = { value = "true" }
      APP_ENV          = { value = "production" }
      LOG_LEVEL        = { value = "INFO" }
    },
    var.gemini_strong_model == "" ? {} : { GEMINI_STRONG_MODEL = { value = var.gemini_strong_model } },
    var.model_price_per_1k_tokens == "" ? {} : { MODEL_PRICE_PER_1K_TOKENS = { value = var.model_price_per_1k_tokens } },
    var.staff_access_code == "" ? {} : { STAFF_ACCESS_CODE = { value = var.staff_access_code } },
    var.stripe_secret_key == "" ? {} : { STRIPE_SECRET_KEY = { value = var.stripe_secret_key } },
    var.stripe_webhook_secret == "" ? {} : { STRIPE_WEBHOOK_SECRET = { value = var.stripe_webhook_secret } },
    var.otel_endpoint == "" ? {} : {
      OTEL_EXPORTER_OTLP_ENDPOINT = { value = var.otel_endpoint }
      OTEL_EXPORTER_OTLP_HEADERS  = { value = var.otel_headers }
    },
    var.langsmith_api_key == "" ? {} : {
      LANGSMITH_TRACING = { value = "true" }
      LANGSMITH_API_KEY = { value = var.langsmith_api_key }
      LANGSMITH_PROJECT = { value = "brightwood-support-agent" }
    },
  )
}

resource "neon_project" "db" {
  name       = "brightwood-support-agent"
  region_id  = "aws-us-west-2"
  pg_version = 17
  org_id     = var.neon_org_id == "" ? null : var.neon_org_id
  # Free tier: the compute suspends when idle and wakes on the next connection.
}

resource "upstash_redis_database" "cache" {
  database_name  = "brightwood-support-agent"
  region         = "global"
  primary_region = "us-west-2"
  tls            = true
  eviction       = false # job messages must never be evicted
}

resource "render_web_service" "api" {
  name              = "brightwood-support-api"
  plan              = "free"
  region            = "oregon"
  health_check_path = "/api/health"

  runtime_source = {
    docker = {
      repo_url        = local.repo_url
      branch          = var.branch
      dockerfile_path = "./Dockerfile"
      context         = "."
      auto_deploy     = true
      build_filter = {
        ignored_paths = ["web/**", "infra/**", "finetune/**", "*.md"]
      }
    }
  }

  env_vars = local.api_env
}

resource "vercel_project" "web" {
  name           = "brightwood-support-agent"
  framework      = "nextjs"
  root_directory = "web"

  git_repository = {
    type              = "github"
    repo              = var.github_repo
    production_branch = var.branch
  }
}

resource "vercel_project_environment_variable" "api_url" {
  project_id = vercel_project.web.id
  key        = "API_URL"
  value      = render_web_service.api.url
  target     = ["production", "preview"]
}
