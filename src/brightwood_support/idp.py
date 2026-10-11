"""A small built-in login provider for the live site.

It makes one RSA key pair when the server starts, signs tokens for named staff with a role,
and publishes the public key. The service verifies every token exactly as it would verify
tokens from a real provider (RS256 only, issuer, audience, expiry, role from the groups claim).
In a real deployment the provider would be Okta, Auth0 or Cognito and only `keys` and the
issuer settings would change. Visitors can sign in as either role to try the approval screen.
"""
from __future__ import annotations

import time

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

ISSUER, AUDIENCE, KID = "brightwood-idp", "brightwood_support", "site-1"


class BuiltInIdP:
    def __init__(self) -> None:
        self._private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.keys = {KID: self._private.public_key()}

    def mint(self, user: str, role: str, minutes: int = 60) -> str:
        claims = {"sub": user, "iss": ISSUER, "aud": AUDIENCE, "exp": int(time.time()) + minutes * 60, "cognito:groups": [role]}
        return jwt.encode(claims, self._private, algorithm="RS256", headers={"kid": KID})
