"""
Serializers for tenant management endpoints.
"""
from rest_framework import serializers
from .models import BusinessTenant, APIKey


class BusinessTenantSerializer(serializers.ModelSerializer):
    """Serializer for BusinessTenant model."""
    
    class Meta:
        model = BusinessTenant
        fields = [
            'tenant_id',
            'name',
            'email',
            'is_active',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['tenant_id', 'created_at', 'updated_at']


class TenantRegistrationSerializer(serializers.Serializer):
    """Serializer for tenant registration."""
    
    name = serializers.CharField(max_length=255)
    email = serializers.EmailField()
    
    def validate_email(self, value):
        """Ensure email is unique."""
        if BusinessTenant.objects.filter(email=value).exists():
            raise serializers.ValidationError(
                "A tenant with this email already exists."
            )
        return value
    
    def create(self, validated_data):
        """Create a new tenant."""
        return BusinessTenant.objects.create(**validated_data)


class APIKeySerializer(serializers.ModelSerializer):
    """Serializer for APIKey model (without exposing the hash)."""
    
    tenant_name = serializers.CharField(source='tenant.name', read_only=True)
    
    class Meta:
        model = APIKey
        fields = [
            'id',
            'tenant_name',
            'name',
            'is_active',
            'created_at',
            'last_used_at',
        ]
        read_only_fields = ['id', 'created_at', 'last_used_at']


class APIKeyCreateSerializer(serializers.Serializer):
    """Serializer for creating a new API key."""
    
    name = serializers.CharField(max_length=100, required=False, allow_blank=True)
    is_test = serializers.BooleanField(default=False)


class APIKeyResponseSerializer(serializers.Serializer):
    """Serializer for API key creation response (includes the plain key)."""
    
    id = serializers.IntegerField()
    name = serializers.CharField()
    api_key = serializers.CharField(help_text="The API key. Save this securely - it won't be shown again!")
    created_at = serializers.DateTimeField()
    warning = serializers.CharField(default="Save this API key securely. It will not be shown again.")

