"""
API Key generation and management service.
Provides secure key generation with cryptographic randomness.
"""
import secrets
import string
from typing import Tuple

from .models import APIKey, BusinessTenant


class APIKeyService:
    """Service for generating and managing API keys."""
    
    # Key prefixes for easy identification
    PREFIX_LIVE = "sk_live_"
    PREFIX_TEST = "sk_test_"
    
    # Key length (excluding prefix) - 32 bytes = 256 bits of entropy
    KEY_LENGTH = 32
    
    @classmethod
    def generate_key(cls, is_test: bool = False) -> str:
        """
        Generate a cryptographically secure API key.
        
        Args:
            is_test: If True, generates a test key with 'sk_test_' prefix.
                     Otherwise, generates a live key with 'sk_live_' prefix.
        
        Returns:
            A secure random API key string.
        """
        prefix = cls.PREFIX_TEST if is_test else cls.PREFIX_LIVE
        # Use secrets for cryptographic randomness
        random_part = secrets.token_urlsafe(cls.KEY_LENGTH)
        return f"{prefix}{random_part}"
    
    @classmethod
    def create_api_key(
        cls,
        tenant: BusinessTenant,
        name: str = "",
        is_test: bool = False
    ) -> Tuple[APIKey, str]:
        """
        Create a new API key for a tenant.
        
        Args:
            tenant: The BusinessTenant to create the key for.
            name: Optional name/description for the key.
            is_test: If True, creates a test key.
        
        Returns:
            A tuple of (APIKey instance, plain_key).
            The plain_key is returned only once and should be shown to the user.
        """
        # Generate the raw key
        plain_key = cls.generate_key(is_test=is_test)
        
        # Create the APIKey instance
        api_key = APIKey(tenant=tenant, name=name)
        api_key.set_key(plain_key)
        api_key.save()
        
        return api_key, plain_key
    
    @classmethod
    def verify_key(cls, raw_key: str) -> APIKey | None:
        """
        Verify an API key and return the associated APIKey instance.
        
        This method iterates through active keys and checks each one.
        For production with many keys, consider using a key prefix index
        or caching strategy.
        
        Args:
            raw_key: The plain API key to verify.
        
        Returns:
            The APIKey instance if valid, None otherwise.
        """
        if not raw_key:
            return None
        
        # Filter active keys from active tenants
        active_keys = APIKey.objects.filter(
            is_active=True,
            tenant__is_active=True
        ).select_related('tenant')
        
        for api_key in active_keys:
            if api_key.check_key(raw_key):
                return api_key
        
        return None
    
    @classmethod
    def deactivate_key(cls, api_key: APIKey) -> None:
        """Deactivate an API key."""
        api_key.is_active = False
        api_key.save(update_fields=['is_active'])
    
    @classmethod
    def rotate_key(
        cls,
        old_key: APIKey,
        name: str = ""
    ) -> Tuple[APIKey, str]:
        """
        Rotate an API key by creating a new one and deactivating the old one.
        
        Args:
            old_key: The APIKey to rotate.
            name: Optional name for the new key.
        
        Returns:
            A tuple of (new APIKey instance, plain_key).
        """
        tenant = old_key.tenant
        is_test = old_key.name.startswith("test") if old_key.name else False
        
        # Create new key
        new_key, plain_key = cls.create_api_key(
            tenant=tenant,
            name=name or f"Rotated from {old_key.name or 'unnamed'}",
            is_test=is_test
        )
        
        # Deactivate old key
        cls.deactivate_key(old_key)
        
        return new_key, plain_key

