from django.contrib import admin
from .models import Template, Notification, DeadLetter


@admin.register(Template)
class TemplateAdmin(admin.ModelAdmin):
    list_display = ["name", "tenant", "channel", "is_active", "created_at"]
    list_filter = ["channel", "is_active", "created_at"]
    search_fields = ["name", "tenant__name"]
    raw_id_fields = ["tenant"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ["id", "tenant", "channel", "to", "status", "created_at", "sent_at"]
    list_filter = ["status", "channel", "created_at"]
    search_fields = ["to", "tenant__name", "id"]
    raw_id_fields = ["tenant", "template"]
    readonly_fields = ["id", "created_at", "updated_at"]
    date_hierarchy = "created_at"


@admin.register(DeadLetter)
class DeadLetterAdmin(admin.ModelAdmin):
    list_display = ["id", "notification", "retry_count", "created_at"]
    list_filter = ["created_at", "retry_count"]
    search_fields = ["notification__id", "reason"]
    raw_id_fields = ["notification"]
    readonly_fields = ["id", "created_at"]
