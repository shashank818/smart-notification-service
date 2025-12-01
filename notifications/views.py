"""
API views for notification management.
"""
from rest_framework import status, viewsets
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.decorators import action
from django.shortcuts import get_object_or_404

from .models import Template, Notification, DeadLetter
from .serializers import (
    TemplateSerializer,
    TemplateCreateSerializer,
    NotificationSerializer,
    NotifyRequestSerializer,
    NotifyResponseSerializer,
    DeadLetterSerializer,
)
from .tasks import send_notification_task


class NotifyView(APIView):
    """
    Send a notification.
    
    POST /v1/notify
    {
        "channel": "email",
        "to": "user@example.com",
        "template": "welcome_email",
        "data": {"name": "John", "company": "Acme"}
    }
    """
    
    def post(self, request):
        if not request.tenant:
            return Response(
                {"error": "Authentication required"},
                status=status.HTTP_401_UNAUTHORIZED
            )
        
        serializer = NotifyRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        data = serializer.validated_data
        tenant = request.tenant
        
        # Resolve template if provided
        template = None
        template_name = data.get('template')
        template_id = data.get('template_id')
        
        if template_name:
            try:
                template = Template.objects.get(
                    tenant=tenant,
                    name=template_name,
                    is_active=True
                )
            except Template.DoesNotExist:
                return Response(
                    {"error": f"Template '{template_name}' not found or inactive"},
                    status=status.HTTP_404_NOT_FOUND
                )
        elif template_id:
            try:
                template = Template.objects.get(
                    tenant=tenant,
                    id=template_id,
                    is_active=True
                )
            except Template.DoesNotExist:
                return Response(
                    {"error": f"Template with ID {template_id} not found or inactive"},
                    status=status.HTTP_404_NOT_FOUND
                )
        
        # Create the notification record
        notification = Notification.objects.create(
            tenant=tenant,
            template=template,
            channel=data['channel'],
            to=data['to'],
            data={
                'template_data': data.get('data', {}),
                'inline_subject': data.get('subject'),
                'inline_body': data.get('body'),
            },
            status='pending'
        )
        
        # Queue the notification for async processing
        send_notification_task.delay(str(notification.id))
        
        # Return response
        return Response(
            {
                "id": notification.id,
                "status": notification.status,
                "channel": notification.channel,
                "to": notification.to,
                "created_at": notification.created_at,
            },
            status=status.HTTP_202_ACCEPTED
        )


class TemplateViewSet(viewsets.ModelViewSet):
    """
    CRUD operations for notification templates.
    
    GET /v1/templates/ - List templates
    POST /v1/templates/ - Create template
    GET /v1/templates/{id}/ - Get template
    PUT /v1/templates/{id}/ - Update template
    DELETE /v1/templates/{id}/ - Delete template
    """
    
    serializer_class = TemplateSerializer
    
    def get_queryset(self):
        """Filter templates by current tenant."""
        if not self.request.tenant:
            return Template.objects.none()
        return Template.objects.filter(tenant=self.request.tenant)
    
    def get_serializer_class(self):
        if self.action == 'create':
            return TemplateCreateSerializer
        return TemplateSerializer
    
    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['request'] = self.request
        return context
    
    def create(self, request, *args, **kwargs):
        if not request.tenant:
            return Response(
                {"error": "Authentication required"},
                status=status.HTTP_401_UNAUTHORIZED
            )
        return super().create(request, *args, **kwargs)
    
    @action(detail=True, methods=['post'])
    def preview(self, request, pk=None):
        """
        Preview a template with sample data.
        
        POST /v1/templates/{id}/preview/
        {"data": {"name": "John", "code": "1234"}}
        """
        template = self.get_object()
        sample_data = request.data.get('data', {})
        
        try:
            from jinja2 import Template as Jinja2Template
            
            rendered_body = Jinja2Template(template.body).render(**sample_data)
            rendered_subject = None
            if template.subject:
                rendered_subject = Jinja2Template(template.subject).render(**sample_data)
            
            return Response({
                "subject": rendered_subject,
                "body": rendered_body,
            })
        except Exception as e:
            return Response(
                {"error": f"Template rendering failed: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST
            )


class NotificationListView(APIView):
    """
    List notifications for the current tenant.
    
    GET /v1/notifications/
    GET /v1/notifications/?status=sent
    GET /v1/notifications/?channel=email
    """
    
    def get(self, request):
        if not request.tenant:
            return Response(
                {"error": "Authentication required"},
                status=status.HTTP_401_UNAUTHORIZED
            )
        
        queryset = Notification.objects.filter(tenant=request.tenant)
        
        # Filter by status
        status_filter = request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        
        # Filter by channel
        channel_filter = request.query_params.get('channel')
        if channel_filter:
            queryset = queryset.filter(channel=channel_filter)
        
        # Limit results
        limit = int(request.query_params.get('limit', 100))
        queryset = queryset[:limit]
        
        serializer = NotificationSerializer(queryset, many=True)
        return Response(serializer.data)


class NotificationDetailView(APIView):
    """
    Get details of a specific notification.
    
    GET /v1/notifications/{id}/
    """
    
    def get(self, request, pk):
        if not request.tenant:
            return Response(
                {"error": "Authentication required"},
                status=status.HTTP_401_UNAUTHORIZED
            )
        
        try:
            notification = Notification.objects.get(
                id=pk,
                tenant=request.tenant
            )
        except Notification.DoesNotExist:
            return Response(
                {"error": "Notification not found"},
                status=status.HTTP_404_NOT_FOUND
            )
        
        serializer = NotificationSerializer(notification)
        return Response(serializer.data)


class DeadLetterListView(APIView):
    """
    List dead letter entries for the current tenant.
    
    GET /v1/dead-letters/
    """
    
    def get(self, request):
        if not request.tenant:
            return Response(
                {"error": "Authentication required"},
                status=status.HTTP_401_UNAUTHORIZED
            )
        
        queryset = DeadLetter.objects.filter(
            notification__tenant=request.tenant
        ).select_related('notification')
        
        limit = int(request.query_params.get('limit', 100))
        queryset = queryset[:limit]
        
        serializer = DeadLetterSerializer(queryset, many=True)
        return Response(serializer.data)
