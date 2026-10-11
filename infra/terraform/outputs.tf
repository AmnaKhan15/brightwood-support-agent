output "api_url" {
  description = "The Python API on Render"
  value       = render_web_service.api.url
}

output "health_url" {
  value = "${render_web_service.api.url}/api/health"
}

output "web_project" {
  description = "The Vercel project; its production URL is shown in the Vercel dashboard after the first deploy"
  value       = vercel_project.web.name
}

output "database_url" {
  description = "For running migrations or evals against production from your machine"
  value       = neon_project.db.connection_uri
  sensitive   = true
}
