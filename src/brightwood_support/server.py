"""The HTTP API (FastAPI). The Next.js site in web/ is the front end; it calls these routes.

    python -m brightwood_support.server            # http://localhost:8000, docs at /api/docs

Settings come from the environment (or a .env file): see .env.example.
"""
from __future__ import annotations

import logging
import os
import secrets
import time

from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, Field

from .auth import AuthError, Forbidden
from .config import env_flag
from .payments import PaymentError
from .service import NoSuchSession, RateLimited, Service
from .shop import NotFound, PolicyError
from .speech import SpeechUnavailable
from .telemetry import request_id, setup_logging, setup_otel

log = logging.getLogger("brightwood.api")
MAX_BODY = 8_000
MAX_WEBHOOK_BODY = 65_536


class ChatIn(BaseModel):
    customer: str = Field(max_length=10)
    message: str = Field(max_length=4000)
    voice: bool = False


class SpeakIn(BaseModel):
    text: str = Field(max_length=4000)


class LoginIn(BaseModel):
    role: str = Field(max_length=30)
    name: str = Field(default="visitor", max_length=30)
    code: str | None = Field(default=None, max_length=200)


class DecisionIn(BaseModel):
    decision: str = Field(pattern="^(approve|reject)$")


class CheckoutIn(BaseModel):
    customer: str = Field(max_length=10)
    product_id: str = Field(max_length=40)


class ConfirmIn(BaseModel):
    session_id: str = Field(max_length=200)


class CustomerIn(BaseModel):
    customer: str = Field(max_length=10)


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
            if "chunked" in request.headers.get("transfer-encoding", "").lower():
                response = _error(411, "length_required", "send a Content-Length; chunked request bodies are not accepted")
            elif int(request.headers.get("content-length") or 0) > limit:
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

    @app.exception_handler(PolicyError)
    async def _policy(_, e):
        return _error(400, "policy", str(e))

    @app.exception_handler(NotFound)
    async def _missing(_, e):
        return _error(404, "not_found", str(e))

    @app.exception_handler(SpeechUnavailable)
    async def _speech(request: Request, e: SpeechUnavailable):
        log.warning("speech unavailable: %s", e)
        return _error(503, "speech_unavailable", "Natural voice is unavailable right now; the browser voice is used instead.")

    @app.exception_handler(PaymentError)
    async def _payment(_, e):
        return _error(502, "payment", f"The payment provider had a problem: {e}")

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

    @app.post("/api/tts", responses={200: {"content": {"audio/wav": {}}}})
    def tts(body: SpeakIn, x_session: str | None = Header(default=None), s: Service = Svc):
        """Read an answer aloud in a natural voice. Returns a WAV file; 503 means use the browser's voice."""
        return Response(s.speak(x_session, body.text), media_type="audio/wav", headers={"Cache-Control": "private, max-age=3600"})

    @app.get("/api/help/search")
    def search(q: str = "", s: Service = Svc):
        return s.search_help(q)

    @app.get("/api/help/articles")
    def articles(s: Service = Svc):
        return s.articles()

    @app.get("/api/products")
    def products(s: Service = Svc):
        return s.products()

    @app.post("/api/checkout")
    def checkout(body: CheckoutIn, x_session: str | None = Header(default=None), s: Service = Svc):
        return s.checkout(x_session, body.customer, body.product_id)

    @app.post("/api/checkout/confirm")
    def confirm_checkout(body: ConfirmIn, x_session: str | None = Header(default=None), s: Service = Svc):
        try:
            return s.confirm_checkout(x_session, body.session_id)
        except PaymentError as e:
            return _error(400, "checkout", str(e))

    @app.post("/api/orders/{order_id}/advance")
    def advance_order(order_id: str, body: CustomerIn, x_session: str | None = Header(default=None), s: Service = Svc):
        return s.advance_order(x_session, body.customer, order_id)

    @app.post("/api/staff/login")
    def login(body: LoginIn, request: Request, s: Service = Svc):
        # request.client is the real peer, or the address a *trusted* proxy reported (FORWARDED_ALLOW_IPS).
        client = request.client.host if request.client else "unknown"
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

    @app.get("/", include_in_schema=False)
    def root():
        """Opening the API server in a browser lands on its interactive docs (Swagger UI)."""
        return RedirectResponse("/api/docs")

    @app.get("/{path:path}", include_in_schema=False)
    def not_found(path: str):
        return _error(404, "not_found", "No such route. This server only answers /api routes; the API docs are at /api/docs and the website is the Next.js app in web/.")

    return app


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv()
    setup_logging(os.environ.get("LOG_LEVEL", "INFO"))
    import uvicorn

    from . import jobs

    service = Service(daily_ai_calls=int(os.environ.get("DAILY_AI_CALLS", "150")))
    app = create_app(service)
    setup_otel(app, os.environ, service.version)
    if env_flag(os.environ, "EMBEDDED_WORKER", default=True):
        jobs.start_embedded_worker()
    port = int(os.environ.get("PORT", "8000"))
    log.info("starting", extra={"ctx": {"port": port, **{k: v for k, v in service.health().items() if k != "gateway"}}})
    # Only trust X-Forwarded-For from the platform's proxy. On Render the app is reachable only through it,
    # so render.yaml sets FORWARDED_ALLOW_IPS="*"; locally nothing is trusted but this machine.
    uvicorn.run(app, host="0.0.0.0", port=port, log_config=None, proxy_headers=True,
                forwarded_allow_ips=os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1"))


if __name__ == "__main__":
    main()
