"""
Email provider implementation using Django's email backend.

This provider is intentionally simple and safe for a POC:
- Uses Django settings for SMTP/SES credentials
- Does not log email body or recipient PII in application logs
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from django.conf import settings
from django.core.mail import EmailMultiAlternatives, get_connection

from .base import BaseProvider, ProviderResult

logger = logging.getLogger(__name__)


class EmailProvider(BaseProvider):
    """Email provider backed by Django's email backend."""

    name = "email"

    def send(
        self,
        to: str,
        subject: str | None,
        body: str,
        channel: str,
    ) -> Dict[str, Any]:
        """
        Send an email using Django's configured email backend.

        Args:
            to: Recipient email address.
            subject: Email subject (may be None; will use a default).
            body: Email body (text).
            channel: Channel name (should be "email").
        """
        if channel != "email":
            raise ValueError(f"EmailProvider can only handle 'email' channel, got '{channel}'")

        if not to:
            raise ValueError("Recipient email address is required")

        if not body:
            raise ValueError("Email body is required")

        subject = subject or "Notification"

        # Ensure we have a from email
        from_email = getattr(settings, "DEFAULT_FROM_EMAIL", None)
        if not from_email:
            raise ValueError("DEFAULT_FROM_EMAIL is not configured")

        # Use Django's email backend connection
        connection = get_connection()

        message = EmailMultiAlternatives(
            subject=subject,
            body=body,
            from_email=from_email,
            to=[to],
            connection=connection,
        )

        try:
            sent_count = message.send(fail_silently=False)

            # Do NOT log body or full recipient; keep logs privacy-friendly
            logger.info(
                "Email sent via EmailProvider",
                extra={
                    "provider": self.name,
                    "to_domain": to.split("@")[-1] if "@" in to else None,
                    "subject_length": len(subject),
                    "body_length": len(body),
                    "sent_count": sent_count,
                },
            )

            result = ProviderResult(
                provider=self.name,
                status="sent" if sent_count > 0 else "not_sent",
                message_id=None,  # Django's backend doesn't expose message IDs generically
                detail=f"Sent to 1 recipient" if sent_count > 0 else "No recipients accepted",
                raw={
                    "sent_count": sent_count,
                    "backend": connection.__class__.__name__,
                },
            )

            return result.to_dict()

        except Exception as exc:
            # Log only minimal info to avoid leaking PII
            logger.error(
                "EmailProvider failed to send email",
                exc_info=True,
                extra={
                    "provider": self.name,
                    "to_domain": to.split("@")[-1] if "@" in to else None,
                },
            )
            raise


