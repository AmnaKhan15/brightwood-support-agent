terraform {
  required_version = ">= 1.6"
  required_providers {
    render = {
      source  = "render-oss/render"
      version = "~> 1.7"
    }
    neon = {
      source  = "kislerdm/neon"
      version = "~> 0.9"
    }
    upstash = {
      source  = "upstash/upstash"
      version = "~> 1.5"
    }
    vercel = {
      source  = "vercel/vercel"
      version = "~> 3.0"
    }
  }
}
