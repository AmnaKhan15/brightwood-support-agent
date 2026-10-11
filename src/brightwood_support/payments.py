"""Payments: how money actually moves when a refund is allowed.

Two providers share one small interface:
  - SimulatedPayments  records a fake payment and refund id. Used when no Stripe key is set.
  - StripePayments     calls Stripe's API in TEST MODE only (it refuses any key that does not
                       start with sk_test_), so no real money can ever move.

The order of events is always: the store's rules pass, a manager approves if the amount needs it,
and only then does code call `refund`. The AI has no tool that reaches this module.

Seeded orders are invented, so they were never really paid. The first time an order is refunded,
a test payment for the order total is created, then refunded. In the Stripe test dashboard you see both.

Webhooks: Stripe tells us later whether a refund succeeded or failed. `verify_webhook` checks the
Stripe-Signature header (HMAC-SHA256 of "timestamp.payload" with the webhook secret) before we
trust the message.

STATUS: tested against a fake HTTP function only. It has NOT been run against the real Stripe API
from the build environment, so field names may need a small fix on the first real call.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from base64 import b64encode
from typing import Callable, Protocol

API = "https://api.stripe.com/v1"
Post = Callable[[str, dict, dict], dict]


class PaymentError(Exception):
    """The payment provider could not complete the call. Nothing was recorded as refunded."""


class Payments(Protocol):
    name: str

    def charge(self, order_id: str, amount_cents: int) -> str: ...
    def refund(self, payment_ref: str, amount_cents: int, idempotency_key: str, order_id: str, reason: str) -> dict: ...


class SimulatedPayments:
    name = "simulated"

    def __init__(self) -> None:
        self._n = 0

    def charge(self, order_id: str, amount_cents: int) -> str:
        return f"sim_pay_{order_id}"

    def refund(self, payment_ref: str, amount_cents: int, idempotency_key: str, order_id: str, reason: str) -> dict:
        self._n += 1
        return {"id": f"sim_re_{order_id}_{self._n}", "status": "succeeded"}


def http_form_post(url: str, headers: dict, form: dict) -> dict:
    data = urllib.parse.urlencode(form).encode()
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/x-www-form-urlencoded", **headers})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        try:
            message = json.loads(error.read()).get("error", {}).get("message", "")
        except ValueError:
            message = ""
        raise PaymentError(f"Stripe returned HTTP {error.code}: {message[:160]}") from None
    except (urllib.error.URLError, TimeoutError) as error:
        raise PaymentError(f"could not reach Stripe: {error}") from None


class StripePayments:
    name = "stripe-test"

    def __init__(self, secret_key: str, post: Post = http_form_post) -> None:
        if not secret_key.startswith("sk_test_"):
            raise ValueError("only Stripe test keys (sk_test_...) are accepted; live keys are refused on purpose")
        self._auth = {"Authorization": "Basic " + b64encode(f"{secret_key}:".encode()).decode()}
        self._post = post

    def charge(self, order_id: str, amount_cents: int) -> str:
        form = {
            "amount": amount_cents, "currency": "usd", "payment_method": "pm_card_visa", "confirm": "true",
            "automatic_payment_methods[enabled]": "true", "automatic_payment_methods[allow_redirects]": "never",
            "metadata[order_id]": order_id, "description": f"Brightwood test order {order_id}",
        }
        data = self._post(f"{API}/payment_intents", {**self._auth, "Idempotency-Key": f"charge-{order_id}-{amount_cents}"}, form)
        if data.get("status") != "succeeded" or "id" not in data:
            raise PaymentError(f"test payment did not succeed (status {data.get('status')!r})")
        return data["id"]

    def refund(self, payment_ref: str, amount_cents: int, idempotency_key: str, order_id: str, reason: str) -> dict:
        form = {"payment_intent": payment_ref, "amount": amount_cents, "reason": "requested_by_customer", "metadata[order_id]": order_id}
        data = self._post(f"{API}/refunds", {**self._auth, "Idempotency-Key": idempotency_key}, form)
        if "id" not in data:
            raise PaymentError("unexpected Stripe reply to the refund")
        return {"id": data["id"], "status": data.get("status", "pending")}


def verify_webhook(payload: bytes, header: str | None, secret: str, tolerance: int = 300, now: Callable[[], float] = time.time) -> dict:
    """Return the event if the signature is valid and fresh, else raise PaymentError."""
    if not header:
        raise PaymentError("missing Stripe-Signature header")
    try:
        parts = dict(p.split("=", 1) for p in header.split(","))
        timestamp = int(parts["t"])
    except (ValueError, KeyError):
        raise PaymentError("malformed Stripe-Signature header") from None
    expected = hmac.new(secret.encode(), f"{timestamp}.".encode() + payload, hashlib.sha256).hexdigest()
    signatures = [p.split("=", 1)[1] for p in header.split(",") if p.startswith("v1=")]
    if not any(hmac.compare_digest(expected, s) for s in signatures):
        raise PaymentError("signature does not match")
    if abs(now() - timestamp) > tolerance:
        raise PaymentError("webhook is too old (possible replay)")
    return json.loads(payload)


def payments_from_env(env) -> Payments:
    key = env.get("STRIPE_SECRET_KEY", "")
    return StripePayments(key) if key else SimulatedPayments()
