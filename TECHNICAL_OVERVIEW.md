## Smart Notification Service – Technical Architecture

This document explains **how the system actually works under the hood**:
- How a `POST /v1/notify` request flows through Django, Celery, Redis, and the email provider
- How **Redis** and **Celery** are wired into the project
- How **PostgreSQL** is used
- How and why we use **Docker** in local development

---

## 1. High-level Component Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                         LOCAL DEV STACK                            │
└─────────────────────────────────────────────────────────────────────┘

          HTTP (REST)
   ┌────────────────────┐
   │  Tenant App / curl │
   └─────────┬──────────┘
             │  X-API-KEY
             ▼
      ┌─────────────┐
      │   Django    │  <- run via `poetry run python manage.py runserver`
      │ + DRF API   │
      └─────┬───────┘
            │
            │ 1) API request
            │   - Auth via API key
            │   - Create Notification row
            │   - Enqueue Celery task
            ▼
      ┌─────────────┐             ┌────────────────────────────┐
      │ PostgreSQL  │◀───────────▶│   Django ORM (models)      │
      │  (Docker)   │             │   - tenants, notifications │
      └─────────────┘             └────────────────────────────┘

            │
            │ Celery task message
            ▼
      ┌─────────────┐
      │   Redis     │  <- broker + result backend (Docker)
      └─────┬───────┘
            │
            │
            ▼
      ┌─────────────┐
      │  Celery     │  <- run via `poetry run celery -A core worker -l info`
      │  Worker(s)  │
      └─────┬───────┘
            │
            │  Provider call (e.g., SMTP/SES)
            ▼
      ┌─────────────┐
      │ Email (SMTP │  <- e.g., Gmail/SES via Django EMAIL_* settings
      │ / SES)      │
      └─────────────┘
```

---

## 2. Request Flow: `POST /v1/notify`

### 2.1. HTTP Request → Django View

1. **Tenant sends a request**:
   - Endpoint: `POST /v1/notify/`
   - Headers:
     - `X-API-KEY: sk_live_...`
     - `Content-Type: application/json`
   - Body example:

```json
{
  "channel": "email",
  "to": "user@example.com",
  "template": "welcome_email",
  "data": {
    "name": "John",
    "company": "Acme Corp"
  }
}
```

2. **Request enters Django’s middleware stack**:
   - Configured in `core/settings.py`:

```45:55:core/settings.py
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    # Custom API key auth and tenant isolation
    'tenants.middleware.APIKeyAuthenticationMiddleware',
    'tenants.middleware.TenantIsolationMiddleware',
]
```

3. **`APIKeyAuthenticationMiddleware`** runs:
   - Implemented in `tenants/middleware.py`
   - Extracts API key from `X-API-KEY` header (`HTTP_X_API_KEY` in `request.META`)
   - Uses `APIKeyService.verify_key(raw_key)` to:
     - Find **active** `APIKey` with a matching hash
     - Ensure `tenant.is_active == True`
   - On success:
     - Sets **`request.tenant`** to the `BusinessTenant` instance
     - Sets **`request.api_key`** to the `APIKey` instance
     - Updates `last_used_at`
   - On failure:
     - Returns `401` or `403` JSON (and does **not** reach the view)

4. **`NotifyView` handles the request**:
   - Implemented in `notifications/views.py` (`NotifyView.post`)
   - Validates payload using `NotifyRequestSerializer` from `notifications/serializers.py`
   - Resolves the template by:
     - `Template.objects.get(tenant=request.tenant, name=template_name, is_active=True)`
   - Creates a `Notification` row with `status="pending"` in PostgreSQL.

### 2.2. Enqueueing the Celery Task

After creating the `Notification` row, the view calls:

```86:96:notifications/views.py
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
```

This does **not** send the email directly. Instead, it sends a Celery message to Redis. The HTTP response to the client is:

```json
{
  "id": "<notification-uuid>",
  "status": "pending",
  "channel": "email",
  "to": "user@example.com",
  "created_at": "..."
}
```

Status `202 Accepted` means: *"we accepted your request and queued it for async processing"*.

---

## 3. Celery + Redis: How Background Processing Works

### 3.1. Where Celery is Configured

**Celery app definition** is in `core/celery.py`:

```1:21:core/celery.py
import os
from celery import Celery

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')

app = Celery('core')

# Load settings with CELERY_ prefix from Django settings
app.config_from_object('django.conf:settings', namespace='CELERY')

# Auto-discover tasks.py in installed apps
app.autodiscover_tasks()

@app.task(bind=True, ignore_result=True)
def debug_task(self):
    print(f'Request: {self.request!r}')
```

**Django settings for Celery** are in `core/settings.py`:

```136:142:core/settings.py
CELERY_BROKER_URL = env("REDIS_URL", default="redis://127.0.0.1:6379/0")
CELERY_RESULT_BACKEND = CELERY_BROKER_URL
```

So both the **broker** (queue transport) and the **result backend** use the same Redis instance, by default:

```text
redis://127.0.0.1:6379/0
```

In local dev, we started this via Docker:

```bash
docker run --name sns-redis -p 6379:6379 -d redis:7-alpine
```

### 3.2. Where the Task Logic Lives

The main task is in `notifications/tasks.py`:

```17:36:notifications/tasks.py
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
    1. Fetch Notification
    2. Render template
    3. Select provider
    4. Send
    5. Update status
    6. Retry or move to dead letter
    """
    from .models import Notification, DeadLetter
    from .providers import get_provider
```

Flow inside the task:

```40:80:notifications/tasks.py
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

    # Mark as processing
    notification.status = 'processing'
    notification.save(update_fields=['status', 'updated_at'])

    try:
        # Render subject/body using Jinja2 and the template data
        subject, body = _render_notification(notification)

        # Choose provider based on channel (email, sms, etc.)
        provider = get_provider(notification.channel)

        # Send via provider (e.g., EmailProvider)
        result = provider.send(
            to=notification.to,
            subject=subject,
            body=body,
            channel=notification.channel,
        )

        # Update DB with success
        notification.status = 'sent'
        notification.sent_at = timezone.now()
        notification.provider_response = result
        notification.save(update_fields=[
            'status', 'sent_at', 'provider_response', 'updated_at'
        ])
```

On **failure**, Celery’s retry mechanism + dead-letter logic kicks in:

```82:97:notifications/tasks.py
    except Exception as e:
        logger.error(f"Failed to send notification {notification_id}: {str(e)}")

        # Store error message
        notification.error_message = str(e)
        notification.save(update_fields=['error_message', 'updated_at'])

        retry_count = self.request.retries

        if retry_count >= MAX_RETRIES:
            # Move to dead letter queue
            _move_to_dead_letter(notification, str(e), retry_count)
        else:
            # Re-raise to trigger Celery retry
            raise
```

And `_move_to_dead_letter` creates a `DeadLetter` row:

```133:144:notifications/tasks.py
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
```

### 3.3. Why Redis is Required

Redis is used as:

- **Celery broker**: Stores the **task queue** where Django publishes messages and Celery workers consume them.
- **Result backend**: Tracks task status and results (we mostly store results directly in the DB, but Celery still uses the backend for internal tracking).

If Redis is **not running** at `127.0.0.1:6379`, you’ll see errors like:

- `redis.exceptions.ConnectionError: Error 111 connecting to 127.0.0.1:6379. Connection refused.`
- `kombu.exceptions.OperationalError: Error 111 connecting to 127.0.0.1:6379.`

That’s exactly what you saw before we started the `sns-redis` container.

---

## 4. Email Provider: How Actual Emails Are Sent

The email provider implementation lives in `notifications/providers/email_provider.py`:

```27:80:notifications/providers/email_provider.py
class EmailProvider(BaseProvider):
    """Email provider backed by Django's email backend."""

    name = "email"

    def send(
        self,
        to: str,
        subject: str | None,
        body: str,
        channel: str,
    ) -> Dict[str, Any]:
        if channel != "email":
            raise ValueError(f"EmailProvider can only handle 'email' channel, got '{channel}'")

        if not to:
            raise ValueError("Recipient email address is required")

        if not body:
            raise ValueError("Email body is required")

        subject = subject or "Notification"

        from_email = getattr(settings, "DEFAULT_FROM_EMAIL", None)
        if not from_email:
            raise ValueError("DEFAULT_FROM_EMAIL is not configured")

        connection = get_connection()

        message = EmailMultiAlternatives(
            subject=subject,
            body=body,
            from_email=from_email,
            to=[to],
            connection=connection,
        )

        sent_count = message.send(fail_silently=False)
```

- It uses **Django’s email backend**, configured in `core/settings.py`:

```133:139:core/settings.py
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = env("EMAIL_HOST", default="")
EMAIL_PORT = env.int("EMAIL_PORT", default=587)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)
DEFAULT_FROM_EMAIL = EMAIL_HOST_USER
```

- The provider **does not log PII** like full email bodies or addresses; logs include only safe metadata (body length, domain, etc.).
- The **result** of `send()` is a `ProviderResult` (in `notifications/providers/base.py`) converted to a dict and stored in `Notification.provider_response`.

---

## 5. PostgreSQL: Where Data Lives

PostgreSQL is configured in `core/settings.py`:

```80:88:core/settings.py
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("DB_NAME", default="notification_service"),
        "USER": env("DB_USER", default="notification_user"),
        "PASSWORD": env("DB_PASSWORD", default="notif_pass"),
        "HOST": env("DB_HOST", default="127.0.0.1"),
        "PORT": env("DB_PORT", default="5432"),
    }
}
```

In local dev, we started a Postgres container with matching credentials:

```bash
docker run --name sns-postgres \
  -e POSTGRES_DB=notification_service \
  -e POSTGRES_USER=notification_user \
  -e POSTGRES_PASSWORD=notif_pass \
  -p 5432:5432 \
  -d postgres:16-alpine
```

**What is stored in Postgres**:

- `BusinessTenant` rows – one per tenant (multi-tenancy)
- `APIKey` rows – hashed keys + metadata
- `Template` rows – per-tenant templates
- `Notification` rows – each send request and its status
- `DeadLetter` rows – permanently failed notifications

All of this is defined in:

- `tenants/models.py`
- `notifications/models.py`

and migrations are in the corresponding `migrations/0001_initial.py` files.

---

## 6. Docker: Why We Use It and How It Fits

In this project, Docker is used only for **infrastructure services**, not for the Django app itself (yet):

- **PostgreSQL container**:
  - Ensures you always have a DB running with known credentials.
  - Isolated from your system Postgres (no conflicts).
  - Started with `sns-postgres` name and mapped to `127.0.0.1:5432`.

- **Redis container**:
  - Provides the Celery broker/backend at `127.0.0.1:6379`.
  - Easy to start/stop/reset while developing.

Benefits:

- Reproducible local environment: anyone can run the containers with same versions.
- Clear separation between **app code** (Python/Poetry) and **infra** (DB, Redis).
- Easy reset if something gets corrupted: `docker rm -f sns-postgres sns-redis`.

You are still running Django and Celery **directly on the host** via Poetry:

```bash
poetry run python manage.py runserver 0.0.0.0:8000
poetry run celery -A core worker -l info
```

Later, you can add a `docker-compose.yml` to start all four services (Django, Celery worker, Postgres, Redis) together.

---

## 7. Full End-to-End Summary

1. **Tenant registration**  
   - `POST /v1/tenants/register/`  
   - Creates `BusinessTenant` and an initial `APIKey` (hash stored, raw shown only once).

2. **Template creation**  
   - `POST /v1/templates/` with `X-API-KEY`  
   - Creates `Template` for that tenant in Postgres.

3. **Notification request**  
   - `POST /v1/notify/` with `X-API-KEY`  
   - Middleware authenticates + sets `request.tenant`.  
   - View validates payload, looks up template, creates `Notification(status="pending")`.  
   - Enqueues `send_notification_task` to **Redis** via Celery.

4. **Background processing**  
   - Celery worker receives task from Redis.  
   - Worker fetches `Notification` + `Template` from Postgres.  
   - Renders body/subject via Jinja2.  
   - Uses `EmailProvider` to send via SMTP/SES (using Django `EMAIL_*` settings).  
   - Updates `Notification` status and `provider_response`.  
   - On repeated failures, moves to `DeadLetter`.

5. **Observability**  
   - `GET /v1/notifications/` – list tenant’s notifications.  
   - `GET /v1/notifications/{uuid}/` – check status of a specific notification.  
   - `GET /v1/dead-letters/` – inspect permanently failed notifications.

This architecture keeps:

- **Security**: API key auth + tenant isolation, keys hashed, PII not logged.
- **Reliability**: Asynchronous retries via Celery, dead-letter queue for permanent failures.
- **Scalability**: Workers can scale independently of Django web processes.


