import uuid
from django.db import models
from django.contrib.auth.hashers import make_password, check_password
from django.utils import timezone


class BusinessTenant(models.Model):
    """
    Represents a customer/tenant in the multi-tenant system.
    Each tenant gets a unique UUID and can have multiple API keys.
    """
    tenant_id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text="Unique identifier for the tenant"
    )
    name = models.CharField(max_length=255, help_text="Business/tenant name")
    email = models.EmailField(help_text="Contact email for the tenant")
    is_active = models.BooleanField(default=True, help_text="Whether the tenant is active")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "business_tenants"
        verbose_name = "Business Tenant"
        verbose_name_plural = "Business Tenants"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.tenant_id})"


class APIKey(models.Model):
    """
    Stores hashed API keys for tenant authentication.
    The actual API key should be shown only once during creation.
    """
    tenant = models.ForeignKey(
        BusinessTenant,
        on_delete=models.CASCADE,
        related_name="api_keys",
        help_text="The tenant this API key belongs to"
    )
    key_hash = models.CharField(
        max_length=255,
        unique=True,
        help_text="Hashed version of the API key"
    )
    name = models.CharField(
        max_length=100,
        blank=True,
        help_text="Optional name/description for this API key"
    )
    is_active = models.BooleanField(default=True, help_text="Whether this API key is active")
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True, help_text="Last time this key was used")

    class Meta:
        db_table = "api_keys"
        verbose_name = "API Key"
        verbose_name_plural = "API Keys"
        ordering = ["-created_at"]

    def __str__(self):
        return f"API Key for {self.tenant.name} ({self.name or 'Unnamed'})"

    def set_key(self, raw_key: str):
        """Hash and store the API key."""
        self.key_hash = make_password(raw_key)

    def check_key(self, raw_key: str) -> bool:
        """Verify if the provided key matches the stored hash."""
        return check_password(raw_key, self.key_hash)

    def mark_used(self):
        """Update the last_used_at timestamp."""
        self.last_used_at = timezone.now()
        self.save(update_fields=["last_used_at"])
