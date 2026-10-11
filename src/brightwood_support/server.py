"""The web server: a small JSON API plus the site's static files (standard library only).

    python -m brightwood_support.server            # http://localhost:8000
Settings come from the environment: PORT, GEMINI_API_KEY, GEMINI_MODEL, GEMINI_STRONG_MODEL, DAILY_AI_CALLS.
"""
from __future__ import annotations

import json
import mimetypes
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .auth import AuthError, Forbidden
from .payments import PaymentError
from .service import NoSuchSession, RateLimited, Service

WEB = Path(__file__).resolve().parents[2] / "web" / "site"
MAX_BODY = 8_000


def make_handler(service: Service):
    class Handler(BaseHTTPRequestHandler):
        server_version = "Brightwood Support Agent"

        def log_message(self, fmt, *args):  # one short line per request, no secrets in it
            print(f"{self.command} {urlparse(self.path).path} -> {args[1] if len(args) > 1 else ''}", flush=True)

        # -- helpers --
        def _send(self, status: int, body: bytes, ctype: str = "application/json", extra: dict | None = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cache-Control", "no-store" if ctype == "application/json" else "no-cache")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, obj) -> None:
            self._send(status, json.dumps(obj, default=str).encode())

        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_BODY:
                raise ValueError("request too large")
            raw = self.rfile.read(n) if n else b"{}"
            data = json.loads(raw or b"{}")
            if not isinstance(data, dict):
                raise ValueError("expected a JSON object")
            return data

        def _sid(self) -> str | None:
            return self.headers.get("X-Session")

        def _guard(self, fn) -> None:
            try:
                fn()
            except NoSuchSession:
                self._json(401, {"error": "session_expired", "message": "Your sandbox expired. Reload the page to start a new one."})
            except RateLimited as e:
                self._json(429, {"error": "rate_limited", "message": str(e)})
            except AuthError as e:
                self._json(401, {"error": "auth", "message": f"Sign-in problem: {e}"})
            except Forbidden as e:
                self._json(403, {"error": "forbidden", "message": f"Not allowed: {e}"})
            except (ValueError, KeyError, json.JSONDecodeError) as e:
                self._json(400, {"error": "bad_request", "message": str(e) or "bad request"})
            except Exception as e:  # noqa: BLE001
                print("ERROR", repr(e), flush=True)
                self._json(500, {"error": "server", "message": "Something went wrong on our side."})

        # -- routes --
        def do_GET(self) -> None:
            url = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            path = url.path
            if path == "/api/health":
                return self._json(200, service.health())
            if path == "/api/state":
                return self._guard(lambda: self._json(200, service.state(self._sid(), q.get("customer"))))
            if m := re.fullmatch(r"/api/table/(\w+)", path):
                return self._guard(lambda: self._json(200, service.table(self._sid(), m.group(1))))
            if path == "/api/help/search":
                return self._guard(lambda: self._json(200, service.search_help(q.get("q", ""))))
            if path == "/api/help/articles":
                return self._json(200, service.articles())
            return self._static(path)

        def do_POST(self) -> None:
            path = urlparse(self.path).path

            def run():
                if path == "/api/stripe/webhook":  # raw body: the signature covers the exact bytes
                    n = int(self.headers.get("Content-Length") or 0)
                    if n > 65_536:
                        raise ValueError("request too large")
                    try:
                        return self._json(200, {"updated": service.handle_webhook(self.rfile.read(n), self.headers.get("Stripe-Signature"))})
                    except PaymentError as e:
                        return self._json(400, {"error": "webhook", "message": str(e)})
                if path == "/api/session":
                    return self._json(200, {"session": service.create_session()})
                data = self._body()
                if path == "/api/session/reset":
                    service.session(self._sid())
                    service.reset(self._sid())
                    return self._json(200, {"ok": True})
                if path == "/api/chat":
                    return self._json(200, service.chat(self._sid(), str(data.get("customer", "")), str(data.get("message", "")), bool(data.get("voice", False))))
                if path == "/api/staff/login":
                    return self._json(200, {"token": service.staff_login(str(data.get("role", "")), str(data.get("name", "visitor"))[:30])})
                if m := re.fullmatch(r"/api/approvals/(\d+)", path):
                    auth = self.headers.get("Authorization", "")
                    token = auth[7:] if auth.startswith("Bearer ") else None
                    return self._json(200, service.decide(self._sid(), token, int(m.group(1)), data.get("decision") == "approve"))
                return self._json(404, {"error": "not_found"})

            self._guard(run)

        def _static(self, path: str) -> None:
            rel = "index.html" if path in ("/", "") else path.lstrip("/")
            target = (WEB / rel).resolve()
            if WEB.resolve() not in target.parents and target != WEB.resolve() or not target.is_file():
                target = WEB / "index.html"  # single page app: unknown paths show the site
            ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype in ("application/javascript", "image/svg+xml"):
                ctype += "; charset=utf-8"
            self._send(200, target.read_bytes(), ctype)

    return Handler


def main() -> None:
    service = Service(daily_ai_calls=int(os.environ.get("DAILY_AI_CALLS", "150")))
    port = int(os.environ.get("PORT", "8000"))
    print(f"Brightwood Support Agent on http://0.0.0.0:{port}  mode={service.health()['mode']}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), make_handler(service)).serve_forever()


if __name__ == "__main__":
    main()
