"""
Celery tasks for async notification processing.
"""
import logging
from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)

# Maximum retry attempts before moving to dead letter
MAX_RETRIES = 3

# Retry delays (exponential backoff in seconds)
RETRY_DELAYS = [60, 300, 900]  # 1 min, 5 min, 15 min


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=900,
    retry_jitter=True,
    max_retries=MAX_RETRIES,
)
def send_notification_task(self, notification_id: str):
    """
    Process and send a notification.
    
    This task:
    1. Fetches the notification from the database
    2. Renders the template (if using a template)
    3. Selects the appropriate provider
    4. Sends the notification
    5. Updates the notification status
    6. On failure, retries or moves to dead letter queue
    """
    from .models import Notification, DeadLetter
    from .providers import get_provider
    
    try:
        notification = Notification.objects.select_related(
            'tenant', 'template'
        ).get(id=notification_id)
    except Notification.DoesNotExist:
        logger.error(f"Notification {notification_id} not found")
        return
    
    # Skip if already processed
    if notification.status in ['sent', 'delivered']:
        logger.info(f"Notification {notification_id} already sent")
        return
    
    # Update status to processing
    notification.status = 'processing'
    notification.save(update_fields=['status', 'updated_at'])
    
    try:
        # Render the message content
        subject, body = _render_notification(notification)
        
        # Get the appropriate provider
        provider = get_provider(notification.channel)
        
        # Send the notification
        result = provider.send(
            to=notification.to,
            subject=subject,
            body=body,
            channel=notification.channel,
        )
        
        # Update notification with success
        notification.status = 'sent'
        notification.sent_at = timezone.now()
        notification.provider_response = result
        notification.save(update_fields=[
            'status', 'sent_at', 'provider_response', 'updated_at'
        ])
        
        logger.info(f"Notification {notification_id} sent successfully")
        
    except Exception as e:
        logger.error(f"Failed to send notification {notification_id}: {str(e)}")
        
        # Update error message
        notification.error_message = str(e)
        notification.save(update_fields=['error_message', 'updated_at'])
        
        # Check if we should retry or move to dead letter
        retry_count = self.request.retries
        
        if retry_count >= MAX_RETRIES:
            # Move to dead letter queue
            _move_to_dead_letter(notification, str(e), retry_count)
        else:
            # Re-raise to trigger retry
            raise


def _render_notification(notification) -> tuple[str, str]:
    """
    Render the notification content.
    
    Returns:
        Tuple of (subject, body)
    """
    from jinja2 import Template as Jinja2Template
    
    data = notification.data or {}
    template_data = data.get('template_data', {})
    
    if notification.template:
        # Render from template
        template = notification.template
        body = Jinja2Template(template.body).render(**template_data)
        subject = None
        if template.subject:
            subject = Jinja2Template(template.subject).render(**template_data)
        return subject, body
    else:
        # Use inline content
        inline_body = data.get('inline_body', '')
        inline_subject = data.get('inline_subject', '')
        
        body = Jinja2Template(inline_body).render(**template_data)
        subject = None
        if inline_subject:
            subject = Jinja2Template(inline_subject).render(**template_data)
        
        return subject, body


def _move_to_dead_letter(notification, reason: str, retry_count: int):
    """Move a failed notification to the dead letter queue."""
    from .models import DeadLetter
    
    notification.status = 'failed'
    notification.save(update_fields=['status', 'updated_at'])
    
    DeadLetter.objects.create(
        notification=notification,
        reason=reason,
        retry_count=retry_count,
    )
    
    logger.warning(
        f"Notification {notification.id} moved to dead letter queue: {reason}"
    )

