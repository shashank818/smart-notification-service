from django.contrib import admin
from .models import BusinessTenant, APIKey


@admin.register(BusinessTenant)
class BusinessTenantAdmin(admin.ModelAdmin):
    list_display = ["tenant_id", "name", "email", "is_active", "created_at"]
    list_filter = ["is_active", "created_at"]
    search_fields = ["name", "email", "tenant_id"]
    readonly_fields = ["tenant_id", "created_at", "updated_at"]


@admin.register(APIKey)
class APIKeyAdmin(admin.ModelAdmin):
    list_display = ["id", "tenant", "name", "is_active", "created_at", "last_used_at"]
    list_filter = ["is_active", "created_at"]
    search_fields = ["tenant__name", "name"]
    readonly_fields = ["key_hash", "created_at", "last_used_at"]
    raw_id_fields = ["tenant"]
