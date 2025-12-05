"""
URL configuration for core project.

All API endpoints are namespaced under /v1/.
"""
from django.contrib import admin
from django.urls import path, include

from tenants.views import (
    TenantRegistrationView,
    TenantDetailView,
    APIKeyListCreateView,
    APIKeyDeactivateView,
)
from notifications.views import (
    NotifyView,
    TemplateViewSet,
    NotificationListView,
    NotificationDetailView,
    DeadLetterListView,
)
from rest_framework.routers import DefaultRouter


router = DefaultRouter()
router.register(r"templates", TemplateViewSet, basename="template")


urlpatterns = [
    path("admin/", admin.site.urls),
    # Health check
    path("health/", lambda request: __import__("django.http").http.JsonResponse({"status": "ok"})),
    # Tenant management
    path("v1/tenants/register/", TenantRegistrationView.as_view(), name="tenant-register"),
    path("v1/tenants/me/", TenantDetailView.as_view(), name="tenant-me"),
    path("v1/api-keys/", APIKeyListCreateView.as_view(), name="api-key-list-create"),
    path(
        "v1/api-keys/<int:pk>/deactivate/",
        APIKeyDeactivateView.as_view(),
        name="api-key-deactivate",
    ),
    # Notifications
    path("v1/notify/", NotifyView.as_view(), name="notify"),
    path("v1/notifications/", NotificationListView.as_view(), name="notification-list"),
    path(
        "v1/notifications/<uuid:pk>/",
        NotificationDetailView.as_view(),
        name="notification-detail",
    ),
    path("v1/dead-letters/", DeadLetterListView.as_view(), name="dead-letter-list"),
    # Template CRUD (router)
    path("v1/", include(router.urls)),
]
