"""
Serializers for notification endpoints.
"""
import re
from rest_framework import serializers
from .models import Template, Notification, DeadLetter


class TemplateSerializer(serializers.ModelSerializer):
    """Serializer for Template model."""
    
    class Meta:
        model = Template
        fields = [
            'id',
            'name',
            'channel',
            'subject',
            'body',
            'variables',
            'is_active',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def validate_name(self, value):
        """Validate template name format (alphanumeric and underscores)."""
        if not re.match(r'^[a-zA-Z][a-zA-Z0-9_]*$', value):
            raise serializers.ValidationError(
                "Template name must start with a letter and contain only "
                "letters, numbers, and underscores."
            )
        return value
    
    def validate(self, data):
        """Validate that email templates have a subject."""
        channel = data.get('channel')
        subject = data.get('subject')
        
        if channel == 'email' and not subject:
            raise serializers.ValidationError({
                'subject': 'Subject is required for email templates.'
            })
        
        return data


class TemplateCreateSerializer(TemplateSerializer):
    """Serializer for creating templates (with tenant from request)."""
    
    def create(self, validated_data):
        """Create template with tenant from request context."""
        request = self.context.get('request')
        if request and hasattr(request, 'tenant'):
            validated_data['tenant'] = request.tenant
        return super().create(validated_data)


class NotificationSerializer(serializers.ModelSerializer):
    """Serializer for Notification model."""
    
    template_name = serializers.CharField(source='template.name', read_only=True)
    
    class Meta:
        model = Notification
        fields = [
            'id',
            'channel',
            'to',
            'template',
            'template_name',
            'data',
            'status',
            'error_message',
            'created_at',
            'updated_at',
            'sent_at',
        ]
        read_only_fields = [
            'id',
            'status',
            'error_message',
            'created_at',
            'updated_at',
            'sent_at',
        ]


class NotifyRequestSerializer(serializers.Serializer):
    """
    Serializer for the notify endpoint request.
    
    Example request:
    {
        "channel": "email",
        "to": "user@example.com",
        "template": "welcome_email",  # or template_id
        "data": {"name": "John", "company": "Acme"}
    }
    
    Or without template (inline content):
    {
        "channel": "email",
        "to": "user@example.com",
        "subject": "Hello!",
        "body": "Hi {{name}}, welcome!",
        "data": {"name": "John"}
    }
    """
    
    CHANNEL_CHOICES = ['email', 'sms', 'whatsapp', 'push']
    
    channel = serializers.ChoiceField(choices=CHANNEL_CHOICES)
    to = serializers.CharField(max_length=255)
    
    # Template reference (by name or ID)
    template = serializers.CharField(required=False, allow_blank=True)
    template_id = serializers.IntegerField(required=False)
    
    # Inline content (if not using template)
    subject = serializers.CharField(max_length=255, required=False, allow_blank=True)
    body = serializers.CharField(required=False, allow_blank=True)
    
    # Template variables
    data = serializers.JSONField(default=dict, required=False)
    
    def validate_to(self, value):
        """Validate recipient address based on channel."""
        # Basic validation - more specific validation happens in validate()
        if not value or not value.strip():
            raise serializers.ValidationError("Recipient address is required.")
        return value.strip()
    
    def validate(self, data):
        """
        Validate the request data.
        - Either template/template_id OR subject+body must be provided
        - Validate recipient format based on channel
        """
        channel = data.get('channel')
        to = data.get('to')
        template = data.get('template')
        template_id = data.get('template_id')
        subject = data.get('subject')
        body = data.get('body')
        
        # Validate template or inline content
        has_template = template or template_id
        has_inline = body
        
        if not has_template and not has_inline:
            raise serializers.ValidationError({
                'template': 'Either template/template_id or body must be provided.'
            })
        
        # Validate email requires subject
        if channel == 'email' and has_inline and not subject:
            raise serializers.ValidationError({
                'subject': 'Subject is required for email notifications.'
            })
        
        # Validate recipient format
        if channel == 'email':
            if not self._is_valid_email(to):
                raise serializers.ValidationError({
                    'to': 'Invalid email address format.'
                })
        elif channel in ['sms', 'whatsapp']:
            if not self._is_valid_phone(to):
                raise serializers.ValidationError({
                    'to': 'Invalid phone number format. Use E.164 format (e.g., +1234567890).'
                })
        
        return data
    
    def _is_valid_email(self, email: str) -> bool:
        """Basic email validation."""
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return bool(re.match(pattern, email))
    
    def _is_valid_phone(self, phone: str) -> bool:
        """Basic phone validation (E.164 format)."""
        pattern = r'^\+[1-9]\d{6,14}$'
        return bool(re.match(pattern, phone))


class NotifyResponseSerializer(serializers.Serializer):
    """Serializer for notify endpoint response."""
    
    id = serializers.UUIDField()
    status = serializers.CharField()
    channel = serializers.CharField()
    to = serializers.CharField()
    created_at = serializers.DateTimeField()


class DeadLetterSerializer(serializers.ModelSerializer):
    """Serializer for DeadLetter model."""
    
    notification_id = serializers.UUIDField(source='notification.id')
    notification_channel = serializers.CharField(source='notification.channel')
    notification_to = serializers.CharField(source='notification.to')
    
    class Meta:
        model = DeadLetter
        fields = [
            'id',
            'notification_id',
            'notification_channel',
            'notification_to',
            'reason',
            'retry_count',
            'created_at',
        ]

