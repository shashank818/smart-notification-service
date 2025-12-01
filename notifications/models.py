import uuid
from django.db import models
from django.core.validators import MinLengthValidator
from tenants.models import BusinessTenant


class Template(models.Model):
    """
    Notification templates per tenant.
    Templates define the structure of notifications with variable placeholders.
    """
    CHANNEL_CHOICES = [
        ("email", "Email"),
        ("sms", "SMS"),
        ("whatsapp", "WhatsApp"),
        ("push", "Push Notification"),
    ]

    tenant = models.ForeignKey(
        BusinessTenant,
        on_delete=models.CASCADE,
        related_name="templates",
        help_text="The tenant this template belongs to"
    )
    name = models.CharField(
        max_length=255,
        help_text="Template name/identifier"
    )
    channel = models.CharField(
        max_length=20,
        choices=CHANNEL_CHOICES,
        help_text="Notification channel type"
    )
    subject = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Subject line (for email/push notifications)"
    )
    body = models.TextField(
        validators=[MinLengthValidator(1)],
        help_text="Template body with variable placeholders (e.g., {{name}}, {{code}})"
    )
    variables = models.JSONField(
        default=dict,
        blank=True,
        help_text="JSON schema or description of expected variables"
    )
    is_active = models.BooleanField(default=True, help_text="Whether this template is active")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "templates"
        verbose_name = "Template"
        verbose_name_plural = "Templates"
        ordering = ["-created_at"]
        unique_together = [["tenant", "name"]]

    def __str__(self):
        return f"{self.name} ({self.channel}) - {self.tenant.name}"


class Notification(models.Model):
    """
    Represents a single notification send request.
    Stores all details about the notification including status and provider responses.
    """
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("processing", "Processing"),
        ("sent", "Sent"),
        ("failed", "Failed"),
        ("delivered", "Delivered"),  # For channels that support delivery confirmation
    ]

    CHANNEL_CHOICES = [
        ("email", "Email"),
        ("sms", "SMS"),
        ("whatsapp", "WhatsApp"),
        ("push", "Push Notification"),
    ]

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text="Unique identifier for the notification"
    )
    tenant = models.ForeignKey(
        BusinessTenant,
        on_delete=models.CASCADE,
        related_name="notifications",
        help_text="The tenant sending this notification"
    )
    template = models.ForeignKey(
        Template,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notifications",
        help_text="Template used for this notification (optional)"
    )
    channel = models.CharField(
        max_length=20,
        choices=CHANNEL_CHOICES,
        help_text="Notification channel"
    )
    to = models.CharField(
        max_length=255,
        help_text="Recipient address (email, phone, device token, etc.)"
    )
    data = models.JSONField(
        default=dict,
        blank=True,
        help_text="Template variables/data for rendering"
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="pending",
        help_text="Current status of the notification"
    )
    provider_response = models.JSONField(
        default=dict,
        blank=True,
        help_text="Response from the provider (SES, Twilio, etc.) including delivery details"
    )
    error_message = models.TextField(
        blank=True,
        null=True,
        help_text="Error message if the notification failed"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    sent_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when the notification was successfully sent"
    )

    class Meta:
        db_table = "notifications"
        verbose_name = "Notification"
        verbose_name_plural = "Notifications"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["tenant", "status"]),
            models.Index(fields=["tenant", "created_at"]),
            models.Index(fields=["status", "created_at"]),
        ]

    def __str__(self):
        return f"Notification {self.id} - {self.channel} to {self.to} ({self.status})"


class DeadLetter(models.Model):
    """
    Stores notifications that have permanently failed after all retry attempts.
    This is useful for debugging and manual intervention.
    """
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )
    notification = models.OneToOneField(
        Notification,
        on_delete=models.CASCADE,
        related_name="dead_letter",
        help_text="The notification that failed permanently"
    )
    reason = models.TextField(
        help_text="Reason why this notification was moved to dead letter queue"
    )
    retry_count = models.IntegerField(
        default=0,
        help_text="Number of retry attempts made before giving up"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "dead_letters"
        verbose_name = "Dead Letter"
        verbose_name_plural = "Dead Letters"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Dead Letter for Notification {self.notification.id}"
