"""
Authentication and tenant isolation middleware.
Extracts API key from request header, validates it, and sets request.tenant.
"""
import logging
from django.http import JsonResponse
from django.utils.deprecation import MiddlewareMixin

from .services import APIKeyService

logger = logging.getLogger(__name__)


class APIKeyAuthenticationMiddleware(MiddlewareMixin):
    """
    Middleware to authenticate requests using API key.
    
    Extracts the API key from the X-API-KEY header, validates it,
    and sets request.tenant and request.api_key for downstream use.
    
    Endpoints that don't require authentication should be listed in EXEMPT_PATHS.
    """
    
    # Header name for API key
    API_KEY_HEADER = "HTTP_X_API_KEY"
    
    # Paths that don't require API key authentication
    EXEMPT_PATHS = [
        "/admin/",
        "/health/",
        "/v1/tenants/register/",  # Tenant registration doesn't need auth
    ]
    
    def process_request(self, request):
        """Process incoming request and authenticate via API key."""
        # Initialize tenant and api_key as None
        request.tenant = None
        request.api_key = None
        
        # Check if path is exempt from authentication
        if self._is_exempt_path(request.path):
            return None
        
        # Skip authentication for non-API paths (like static files)
        if not request.path.startswith("/v1/"):
            return None
        
        # Extract API key from header
        api_key_raw = request.META.get(self.API_KEY_HEADER)
        
        if not api_key_raw:
            return JsonResponse(
                {
                    "error": "Authentication required",
                    "detail": "Missing X-API-KEY header"
                },
                status=401
            )
        
        # Verify the API key
        api_key = APIKeyService.verify_key(api_key_raw)
        
        if not api_key:
            logger.warning(
                f"Invalid API key attempt from {request.META.get('REMOTE_ADDR')}"
            )
            return JsonResponse(
                {
                    "error": "Invalid API key",
                    "detail": "The provided API key is invalid or inactive"
                },
                status=401
            )
        
        # Check if tenant is active
        if not api_key.tenant.is_active:
            logger.warning(
                f"Inactive tenant access attempt: {api_key.tenant.tenant_id}"
            )
            return JsonResponse(
                {
                    "error": "Tenant inactive",
                    "detail": "Your account has been deactivated"
                },
                status=403
            )
        
        # Set tenant and api_key on request for downstream use
        request.tenant = api_key.tenant
        request.api_key = api_key
        
        # Update last_used_at (async in production for performance)
        api_key.mark_used()
        
        return None
    
    def _is_exempt_path(self, path: str) -> bool:
        """Check if the path is exempt from authentication."""
        for exempt_path in self.EXEMPT_PATHS:
            if path.startswith(exempt_path):
                return True
        return False


class TenantIsolationMiddleware(MiddlewareMixin):
    """
    Middleware to ensure tenant isolation in responses.
    
    This middleware can be extended to add tenant context to responses
    or perform additional isolation checks.
    """
    
    def process_response(self, request, response):
        """Add tenant context headers to response if tenant is set."""
        if hasattr(request, 'tenant') and request.tenant:
            # Add tenant ID to response headers (useful for debugging)
            response['X-Tenant-ID'] = str(request.tenant.tenant_id)
        return response

