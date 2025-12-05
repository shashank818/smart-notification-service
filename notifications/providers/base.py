"""
Base provider interface.

Each provider implementation should inherit from `BaseProvider` and
implement the `send` method.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class ProviderResult:
    """
    Standardized result from a provider call.

    This is stored in Notification.provider_response as JSON.
    """

    provider: str
    status: str
    message_id: str | None = None
    detail: str | None = None
    raw: Dict[str, Any] | None = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "status": self.status,
            "message_id": self.message_id,
            "detail": self.detail,
            "raw": self.raw or {},
        }


class BaseProvider:
    """
    Abstract base provider.

    Concrete providers must implement `send`.
    """

    name: str = "base"

    def send(
        self,
        to: str,
        subject: str | None,
        body: str,
        channel: str,
    ) -> Dict[str, Any]:
        """
        Send a notification.

        Returns:
            A dict that will be stored in Notification.provider_response.
        """
        raise NotImplementedError("send() must be implemented by subclasses")


