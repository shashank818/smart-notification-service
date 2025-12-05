"""
Provider factory and registration.

This module exposes a single `get_provider(channel)` function that returns
an appropriate provider implementation for the given channel.
"""

from .base import BaseProvider
from .email_provider import EmailProvider


def get_provider(channel: str) -> BaseProvider:
    """
    Return a provider instance for the given channel.

    For the POC we implement:
    - email: EmailProvider (Django's SMTP/SES backend)

    Other channels (sms, whatsapp, push) raise NotImplementedError for now.
    """
    normalized = (channel or "").lower()

    if normalized == "email":
        return EmailProvider()

    # Placeholders for future implementations
    if normalized in {"sms", "whatsapp", "push"}:
        raise NotImplementedError(f"Provider for channel '{normalized}' is not implemented yet.")

    raise ValueError(f"Unsupported channel: {channel}")


