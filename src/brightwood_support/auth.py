"""Login and roles: verify a signed token, then map its groups to a role.

The service never trusts a caller's claim about who they are. It checks the
token's signature against the identity provider's public key (for Amazon
Cognito, the keys published at the user pool's JWKS URL), then checks who
issued it, who it is for, and that it has not expired.

Role comes from the token's `cognito:groups` claim, so a person's authority is
set in the identity provider, not in our code.
"""
from __future__ import annotations

from typing import Any, Mapping

import jwt

from .approvals import ROLE_RANK


class AuthError(Exception):
    """The token is missing, invalid or expired. Maps to HTTP 401."""


class Forbidden(Exception):
    """The token is valid but the role is too low. Maps to HTTP 403."""


def verify_token(
    token: str | None,
    keys: Mapping[str, Any],
    *,
    audience: str,
    issuer: str,
    leeway: float = 0,
) -> dict:
    """Return the token's claims, or raise AuthError.

    keys maps a key id (`kid`) to a public key. Only RS256 is accepted, and it is
    pinned here. That blocks the "algorithm confusion" attack, where an attacker
    signs a token with HS256 using the public key as the secret, and the `none`
    algorithm, which has no signature at all.
    """
    if not token:
        raise AuthError("missing token")
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise AuthError(f"malformed token: {exc}") from None
    if header.get("alg") != "RS256":
        raise AuthError(f"algorithm {header.get('alg')!r} is not allowed")
    key = keys.get(header.get("kid", ""))
    if key is None:
        raise AuthError("unknown signing key")
    try:
        return jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=audience,
            issuer=issuer,
            leeway=leeway,
            options={"require": ["exp", "iss", "aud", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise AuthError(str(exc)) from None


def role_of(claims: Mapping[str, Any]) -> str | None:
    """The highest known role among the token's groups, or None."""
    groups = claims.get("cognito:groups") or []
    known = [g for g in groups if g in ROLE_RANK]
    return max(known, key=ROLE_RANK.__getitem__) if known else None


def require_role(claims: Mapping[str, Any], minimum: str) -> str:
    """Return the caller's role, or raise Forbidden if it is below `minimum`."""
    role = role_of(claims)
    if role is None or ROLE_RANK[role] < ROLE_RANK[minimum]:
        raise Forbidden(f"{minimum!r} or higher is required")
    return role
