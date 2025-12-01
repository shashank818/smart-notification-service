"""
API views for tenant management.
"""
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response

from .models import BusinessTenant, APIKey
from .serializers import (
    BusinessTenantSerializer,
    TenantRegistrationSerializer,
    APIKeySerializer,
    APIKeyCreateSerializer,
    APIKeyResponseSerializer,
)
from .services import APIKeyService


class TenantRegistrationView(APIView):
    """
    Register a new tenant and receive an API key.
    
    POST /v1/tenants/register/
    {
        "name": "Acme Corp",
        "email": "admin@acmecorp.com"
    }
    """
    
    def post(self, request):
        serializer = TenantRegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        # Create the tenant
        tenant = serializer.save()
        
        # Create an initial API key for the tenant
        api_key, plain_key = APIKeyService.create_api_key(
            tenant=tenant,
            name="Initial API Key"
        )
        
        return Response(
            {
                "tenant": BusinessTenantSerializer(tenant).data,
                "api_key": {
                    "id": api_key.id,
                    "name": api_key.name,
                    "key": plain_key,
                    "warning": "Save this API key securely. It will not be shown again!"
                }
            },
            status=status.HTTP_201_CREATED
        )


class TenantDetailView(APIView):
    """
    Get current tenant details.
    
    GET /v1/tenants/me/
    """
    
    def get(self, request):
        if not request.tenant:
            return Response(
                {"error": "Authentication required"},
                status=status.HTTP_401_UNAUTHORIZED
            )
        
        serializer = BusinessTenantSerializer(request.tenant)
        return Response(serializer.data)


class APIKeyListCreateView(APIView):
    """
    List and create API keys for the current tenant.
    
    GET /v1/api-keys/
    POST /v1/api-keys/
    """
    
    def get(self, request):
        """List all API keys for the current tenant."""
        if not request.tenant:
            return Response(
                {"error": "Authentication required"},
                status=status.HTTP_401_UNAUTHORIZED
            )
        
        api_keys = APIKey.objects.filter(tenant=request.tenant)
        serializer = APIKeySerializer(api_keys, many=True)
        return Response(serializer.data)
    
    def post(self, request):
        """Create a new API key for the current tenant."""
        if not request.tenant:
            return Response(
                {"error": "Authentication required"},
                status=status.HTTP_401_UNAUTHORIZED
            )
        
        serializer = APIKeyCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        api_key, plain_key = APIKeyService.create_api_key(
            tenant=request.tenant,
            name=serializer.validated_data.get('name', ''),
            is_test=serializer.validated_data.get('is_test', False)
        )
        
        return Response(
            {
                "id": api_key.id,
                "name": api_key.name,
                "api_key": plain_key,
                "created_at": api_key.created_at,
                "warning": "Save this API key securely. It will not be shown again!"
            },
            status=status.HTTP_201_CREATED
        )


class APIKeyDeactivateView(APIView):
    """
    Deactivate an API key.
    
    POST /v1/api-keys/{id}/deactivate/
    """
    
    def post(self, request, pk):
        if not request.tenant:
            return Response(
                {"error": "Authentication required"},
                status=status.HTTP_401_UNAUTHORIZED
            )
        
        try:
            api_key = APIKey.objects.get(pk=pk, tenant=request.tenant)
        except APIKey.DoesNotExist:
            return Response(
                {"error": "API key not found"},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Prevent deactivating the key being used for this request
        if request.api_key and request.api_key.id == api_key.id:
            return Response(
                {"error": "Cannot deactivate the API key currently in use"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        APIKeyService.deactivate_key(api_key)
        
        return Response(
            {"message": "API key deactivated successfully"},
            status=status.HTTP_200_OK
        )
