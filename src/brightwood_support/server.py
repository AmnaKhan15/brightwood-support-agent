"""The HTTP API (FastAPI). The Next.js site in web/ is the front end; it calls these routes.

    python -m brightwood_support.server            # http://localhost:8000, docs at /api/docs

Settings come from the environment (or a .env file): see .env.example.
"""
from __future__ import annotations

import logging
import os
import secrets
import time

if __name__ == "__main__":  # load .env before anything reads the environment (jobs.py picks its broker at import)
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .auth import AuthError, Forbidden
from .payments import PaymentError
from .service import NoSuchSession, RateLimited, Service
from .telemetry import request_id, setup_logging, setup_otel

log = logging.getLogger("brightwood.api")
MAX_BODY = 8_000
MAX_WEBHOOK_BODY = 65_536


class ChatIn(BaseModel):
    customer: str = Field(max_length=10)
    message: str = Field(max_length=4000)
    voice: bool = False


class LoginIn(BaseModel):
    role: str = Field(max_length=30)
    name: str = Field(default="visitor", max_length=30)
    code: str | None = Field(default=None, max_length=200)


class DecisionIn(BaseModel):
    decision: str = Field(pattern="^(approve|reject)$")


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": code, "message": message}, status_code=status)


def create_app(service: Service | None = None, env=os.environ) -> FastAPI:
    app = FastAPI(title="Brightwood Support Agent API", version="2.0", docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)
    app.state.service = service

    def svc() -> Service:
        if app.state.service is None:
            app.state.service = Service(daily_ai_calls=int(env.get("DAILY_AI_CALLS", "150")), env=env)
        return app.state.service

    origins = [o.strip() for o in env.get("CORS_ORIGINS", "").split(",") if o.strip()]
    if origins:  # only needed when the browser calls the API directly; the Next.js proxy is same-origin
        app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST"],
                           allow_headers=["Content-Type", "X-Session", "Authorization"])

    @app.middleware("http")
    async def guard(request: Request, call_next):
        rid = request.headers.get("X-Request-ID") or secrets.token_hex(8)
        token = request_id.set(rid[:64])
        started = time.perf_counter()
        try:
            limit = MAX_WEBHOOK_BODY if request.url.path == "/api/stripe/webhook" else MAX_BODY
            if int(request.headers.get("content-length") or 0) > limit:
                response = _error(400, "bad_request", "request too large")
            else:
                response = await call_next(request)
        finally:
            request_id.reset(token)
        response.headers.update({"X-Request-ID": rid[:64], "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
                                 "Cache-Control": "no-store", "X-Frame-Options": "DENY"})
        if request.url.path != "/api/health":
            log.info("request", extra={"ctx": {"request_id": rid[:64], "method": request.method, "path": request.url.path,
                                               "status": response.status_code, "ms": round((time.perf_counter() - started) * 1000, 1)}})
        return response

    # Errors become small JSON bodies with a stable "error" code the front end can act on.
    @app.exception_handler(NoSuchSession)
    async def _expired(_, __):
        return _error(401, "session_expired", "Your sandbox expired. Reload the page to start a new one.")

    @app.exception_handler(RateLimited)
    async def _limited(_, e):
        return _error(429, "rate_limited", str(e))

    @app.exception_handler(AuthError)
    async def _auth(_, e):
        return _error(401, "auth", f"Sign-in problem: {e}")

    @app.exception_handler(Forbidden)
    async def _forbidden(_, e):
        return _error(403, "forbidden", f"Not allowed: {e}")

    @app.exception_handler(RequestValidationError)
    async def _invalid(_, e):
        first = e.errors()[0] if e.errors() else {}
        where = ".".join(str(p) for p in first.get("loc", []) if p != "body")
        return _error(400, "bad_request", f"{where}: {first.get('msg', 'invalid')}" if where else "bad request")

    @app.exception_handler(ValueError)
    async def _value(_, e):
        return _error(400, "bad_request", str(e) or "bad request")

    @app.exception_handler(KeyError)
    async def _key(_, e):
        return _error(400, "bad_request", f"unknown {e}")

    @app.exception_handler(Exception)
    async def _crash(_, e):
        log.exception("unhandled error")
        return _error(500, "server", "Something went wrong on our side.")

    Svc = Depends(svc)  # noqa: N806

    @app.get("/api/health")
    def health(s: Service = Svc):
        return s.health()

    @app.get("/api/metrics")
    def metrics(days: int = 7, s: Service = Svc):
        return s.metrics(days)

    @app.post("/api/session")
    def new_session(s: Service = Svc):
        return {"session": s.create_session()}

    @app.post("/api/session/reset")
    def reset(x_session: str | None = Header(default=None), s: Service = Svc):
        s.session(x_session)
        s.reset(x_session)
        return {"ok": True}

    @app.get("/api/state")
    def state(customer: str | None = None, x_session: str | None = Header(default=None), s: Service = Svc):
        return s.state(x_session, customer)

    @app.get("/api/table/{name}")
    def table(name: str, x_session: str | None = Header(default=None), s: Service = Svc):
        return s.table(x_session, name)

    @app.post("/api/chat")
    def chat(body: ChatIn, x_session: str | None = Header(default=None), s: Service = Svc):
        return s.chat(x_session, body.customer, body.message, body.voice)

    @app.get("/api/help/search")
    def search(q: str = "", s: Service = Svc):
        return s.search_help(q)

    @app.get("/api/help/articles")
    def articles(s: Service = Svc):
        return s.articles()

    @app.post("/api/staff/login")
    def login(body: LoginIn, request: Request, s: Service = Svc):
        client = request.headers.get("x-forwarded-for", request.client.host if request.client else "unknown").split(",")[0].strip()
        return {"token": s.staff_login(body.role, body.name, body.code, client)}

    @app.post("/api/approvals/{approval_id}")
    def decide(approval_id: int, body: DecisionIn, x_session: str | None = Header(default=None),
               authorization: str | None = Header(default=None), s: Service = Svc):
        token = authorization[7:] if authorization and authorization.startswith("Bearer ") else None
        return s.decide(x_session, token, approval_id, body.decision == "approve")

    @app.post("/api/stripe/webhook")
    async def webhook(request: Request, stripe_signature: str | None = Header(default=None), s: Service = Svc):
        payload = await request.body()  # raw bytes: the signature covers them exactly
        try:
            return s.handle_webhook(payload, stripe_signature)
        except PaymentError as e:
            return _error(400, "webhook", str(e))

    @app.get("/{path:path}", include_in_schema=False)
    def not_found(path: str):
        return _error(404, "not_found", "The website is served by the Next.js app in web/; this server only answers /api routes.")

    return app


def main() -> None:
    setup_logging(os.environ.get("LOG_LEVEL", "INFO"))
    import uvicorn

    from . import jobs

    service = Service(daily_ai_calls=int(os.environ.get("DAILY_AI_CALLS", "150")))
    app = create_app(service)
    setup_otel(app, os.environ, service.version)
    if os.environ.get("EMBEDDED_WORKER", "true").lower() in ("1", "true", "yes"):
        jobs.start_embedded_worker()
    port = int(os.environ.get("PORT", "8000"))
    log.info("starting", extra={"ctx": {"port": port, **{k: v for k, v in service.health().items() if k != "gateway"}}})
    uvicorn.run(app, host="0.0.0.0", port=port, log_config=None, proxy_headers=True, forwarded_allow_ips="*")


if __name__ == "__main__":
    main()
