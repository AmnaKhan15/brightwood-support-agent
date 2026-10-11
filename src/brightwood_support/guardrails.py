"""Guardrails: hide personal and payment data, and cap how much the AI may use.

Policy (data/help/privacy_and_security.md): never repeat full card numbers, passwords or
other people's email addresses. Chat messages and tool results can contain them, so
everything the AI reads and writes is masked.
"""
from __future__ import annotations

import re

_CARD = re.compile(r"\b(?:\d[ -]?){12,15}(\d{4})\b")
_KEY_VALUE = re.compile(r"(?i)(?<![A-Za-z])(password|passwd|secret|token|api[_-]?key|cvv|cvc)\b(\s*[=:]\s*)([^\s,;\"']+)")
_EMAIL = re.compile(r"\b([A-Za-z0-9._%+-])[A-Za-z0-9._%+-]*@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")


def mask_private(text: str, keep_emails: set[str] | None = None) -> str:
    """Mask card numbers (keeping the last 4 digits), `name=value` secrets and email addresses.

    Emails in `keep_emails` (the signed-in customer's own) are left alone.
    Known limits: it recognises three common shapes. A card number written in words,
    split over several messages, or a secret in another format is not caught.
    """
    keep = {e.lower() for e in (keep_emails or set())}
    text = _CARD.sub(lambda m: f"**** **** **** {m.group(1)}", text)
    text = _KEY_VALUE.sub(lambda m: f"{m.group(1)}{m.group(2)}****", text)

    def email(m: re.Match) -> str:
        return m.group(0) if m.group(0).lower() in keep else f"{m.group(1)}***@{m.group(2)}"

    return _EMAIL.sub(email, text)


class BudgetExceeded(Exception):
    """The run used more tokens than allowed."""


class TokenBudget:
    def __init__(self, max_tokens: int) -> None:
        self.max_tokens = max_tokens
        self.used = 0

    def charge(self, tokens: int) -> None:
        self.used += tokens
        if self.used > self.max_tokens:
            raise BudgetExceeded(f"used {self.used} of {self.max_tokens} tokens")


_INJECTION = re.compile(
    r"ignore (all |your |the |previous |any )*(rules|instructions)|\bsystem:|you are now|developer mode|pretend|reveal (your )?(prompt|instructions)",
    re.I,
)


def looks_like_injection(text: str) -> bool:
    """Flag a message that tries to change the assistant's rules.

    This only raises a flag for the audit log and the screen. It is not the protection: the
    protection is that the rules live in the store and the approval gate, below the AI.
    Known limit: it matches common phrasings, so a cleverly worded attack is not flagged.
    """
    return bool(_INJECTION.search(text))
