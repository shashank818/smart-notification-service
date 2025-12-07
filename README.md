# Smart Notification Service (NaaS)

A multi-tenant **Notification-as-a-Service (NaaS)** that exposes a unified REST API to send **Email, SMS, WhatsApp, and Push** messages. Tenants register and receive API keys, create templates, then send notifications via `POST /v1/notify`.

## Tech Stack

- **Backend**: Django + Django REST Framework
- **Database**: PostgreSQL
- **Queue**: Celery + Redis
- **Providers**: SES/SMTP (Email), Twilio/MSG91 (SMS), FCM (Push)

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Data Models](#data-models)
3. [Security Architecture](#security-architecture)
4. [API Flow](#api-flow)
5. [Implementation Checklist](#implementation-checklist)
6. [Getting Started](#getting-started)
7. [API Reference](#api-reference)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                           SMART NOTIFICATION SERVICE                                │
└─────────────────────────────────────────────────────────────────────────────────────┘

    TENANTS                         BACKEND                           PROVIDERS
    ═══════                         ═══════                           ═════════

 ┌──────────┐                   ┌─────────────┐                    ┌──────────┐
 │ Tenant A │──┐                │             │                    │   SES    │
 │ (API Key)│  │                │   Django    │                    │  (Email) │
 └──────────┘  │   REST API     │   + DRF     │    Provider        └──────────┘
               ├───────────────▶│             │────Adapters───────▶┌──────────┐
 ┌──────────┐  │  X-API-KEY     │             │                    │  Twilio  │
 │ Tenant B │──┤                │             │                    │  (SMS)   │
 │ (API Key)│  │                └──────┬──────┘                    └──────────┘
 └──────────┘  │                       │                           ┌──────────┐
               │                       │ Task Queue                │   FCM    │
 ┌──────────┐  │                       ▼                           │  (Push)  │
 │ Tenant C │──┘                ┌─────────────┐                    └──────────┘
 │ (API Key)│                   │   Celery    │                    ┌──────────┐
 └──────────┘                   │   Workers   │                    │  MSG91   │
                                └──────┬──────┘                    │(WhatsApp)│
                                       │                           └──────────┘
                                       ▼
                                ┌─────────────┐
                                │    Redis    │
                                │   (Broker)  │
                                └─────────────┘

                                ┌─────────────┐
                                │ PostgreSQL  │
                                │ (Database)  │
                                └─────────────┘
```

---

## Data Models

### Entity Relationship Diagram

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                              DATA MODEL RELATIONSHIPS                               │
└─────────────────────────────────────────────────────────────────────────────────────┘

    ┌─────────────────────┐
    │   BusinessTenant    │
    │─────────────────────│
    │ tenant_id (UUID PK) │
    │ name                │
    │ email               │
    │ is_active           │
    │ created_at          │
    │ updated_at          │
    └──────────┬──────────┘
               │
               │ 1:N
               │
    ┌──────────┴──────────┬─────────────────────┐
    │                     │                     │
    ▼                     ▼                     ▼
┌─────────────┐    ┌─────────────┐      ┌─────────────┐
│   APIKey    │    │  Template   │      │Notification │
│─────────────│    │─────────────│      │─────────────│
│ id (PK)     │    │ id (PK)     │      │ id (UUID PK)│
│ tenant (FK) │    │ tenant (FK) │      │ tenant (FK) │
│ key_hash    │    │ name        │      │ template(FK)│◄──┐
│ name        │    │ channel     │      │ channel     │   │
│ is_active   │    │ subject     │      │ to          │   │
│ created_at  │    │ body        │      │ data (JSON) │   │
│ last_used_at│    │ variables   │      │ status      │   │
└─────────────┘    │ is_active   │      │ provider_   │   │
                   │ created_at  │      │  response   │   │
                   │ updated_at  │      │ error_msg   │   │
                   └──────┬──────┘      │ created_at  │   │
                          │             │ updated_at  │   │
                          │ 1:N         │ sent_at     │   │
                          └────────────▶└──────┬──────┘   │
                                               │          │
                                               │ 1:1      │
                                               ▼          │
                                        ┌─────────────┐   │
                                        │ DeadLetter  │   │
                                        │─────────────│   │
                                        │ id (UUID PK)│   │
                                        │notification │───┘
                                        │  (FK)       │
                                        │ reason      │
                                        │ retry_count │
                                        │ created_at  │
                                        └─────────────┘
```

### Model Field Details

#### 1. BusinessTenant (`tenants/models.py`)

Represents a customer/organization in the multi-tenant system.

| Field | Type | Description |
|-------|------|-------------|
| `tenant_id` | UUID (PK) | Unique identifier, auto-generated |
| `name` | CharField(255) | Business/tenant name (e.g., "Acme Corp") |
| `email` | EmailField | Contact email for the tenant |
| `is_active` | Boolean | Whether the tenant can use the service |
| `created_at` | DateTime | Auto-set on creation |
| `updated_at` | DateTime | Auto-updated on save |

#### 2. APIKey (`tenants/models.py`)

Stores hashed API keys for tenant authentication.

| Field | Type | Description |
|-------|------|-------------|
| `id` | AutoField (PK) | Primary key |
| `tenant` | FK → BusinessTenant | Owner tenant (CASCADE delete) |
| `key_hash` | CharField(255) | Hashed API key (PBKDF2-SHA256) |
| `name` | CharField(100) | Optional label (e.g., "Production Key") |
| `is_active` | Boolean | Whether the key is active |
| `created_at` | DateTime | Auto-set on creation |
| `last_used_at` | DateTime | Last usage timestamp |

**Methods:**
- `set_key(raw_key)`: Hash and store the API key
- `check_key(raw_key)`: Verify a key against the hash
- `mark_used()`: Update `last_used_at` timestamp

#### 3. Template (`notifications/models.py`)

Notification templates with variable placeholders.

| Field | Type | Description |
|-------|------|-------------|
| `id` | AutoField (PK) | Primary key |
| `tenant` | FK → BusinessTenant | Owner tenant (CASCADE delete) |
| `name` | CharField(255) | Template identifier (e.g., "otp_sms") |
| `channel` | CharField(20) | One of: `email`, `sms`, `whatsapp`, `push` |
| `subject` | CharField(255) | Subject line (for email/push) |
| `body` | TextField | Template body with `{{variable}}` placeholders |
| `variables` | JSONField | Schema of expected variables |
| `is_active` | Boolean | Whether the template is active |
| `created_at` | DateTime | Auto-set on creation |
| `updated_at` | DateTime | Auto-updated on save |

**Example Template Body:**
```
Hello {{name}}, your OTP is {{code}}. Valid for {{minutes}} minutes.
```

#### 4. Notification (`notifications/models.py`)

Represents a single notification send request.

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID (PK) | Unique identifier (prevents enumeration) |
| `tenant` | FK → BusinessTenant | Sending tenant (CASCADE delete) |
| `template` | FK → Template | Template used (SET_NULL on delete) |
| `channel` | CharField(20) | One of: `email`, `sms`, `whatsapp`, `push` |
| `to` | CharField(255) | Recipient (email, phone, device token) |
| `data` | JSONField | Template variables for rendering |
| `status` | CharField(20) | One of: `pending`, `processing`, `sent`, `failed`, `delivered` |
| `provider_response` | JSONField | Provider response (message ID, status, etc.) |
| `error_message` | TextField | Error details if failed |
| `created_at` | DateTime | Auto-set on creation |
| `updated_at` | DateTime | Auto-updated on save |
| `sent_at` | DateTime | Timestamp when successfully sent |

**Database Indexes:**
- `(tenant, status)` — Filter by tenant and status
- `(tenant, created_at)` — Tenant notifications by time
- `(status, created_at)` — Status-based queries

#### 5. DeadLetter (`notifications/models.py`)

Stores notifications that permanently failed after all retry attempts.

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID (PK) | Unique identifier |
| `notification` | OneToOne → Notification | The failed notification |
| `reason` | TextField | Failure reason |
| `retry_count` | Integer | Number of retry attempts made |
| `created_at` | DateTime | Auto-set on creation |

---

## Security Architecture

### 1. API Key Authentication Flow

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                           API KEY AUTHENTICATION FLOW                               │
└─────────────────────────────────────────────────────────────────────────────────────┘

 TENANT REGISTRATION                              API REQUEST
 ══════════════════                              ═══════════

 ┌──────────┐                                    ┌──────────┐
 │  Tenant  │                                    │  Tenant  │
 │ Registers│                                    │ App/Code │
 └────┬─────┘                                    └────┬─────┘
      │                                               │
      │ 1. Create account                             │ 1. POST /v1/notify
      ▼                                               │    Header: X-API-KEY: sk_live_abc123...
 ┌──────────┐                                         ▼
 │  Backend │                                    ┌──────────┐
 │ generates│                                    │  Nginx/  │
 │ API Key  │                                    │  Django  │
 └────┬─────┘                                    └────┬─────┘
      │                                               │
      │ 2. Generate secure random key                 │ 2. Extract X-API-KEY header
      │    sk_live_abc123xyz789...                    ▼
      │                                          ┌──────────┐
      │ 3. Hash with PBKDF2-SHA256               │   API    │
      │    pbkdf2_sha256$...                     │   Key    │
      │                                          │Middleware│
      │ 4. Store ONLY the hash                   └────┬─────┘
      │    in database                                │
      ▼                                               │ 3. Hash incoming key
 ┌──────────┐                                         │    Compare with stored hashes
 │ Database │                                         │
 │ APIKey   │◄────────────────────────────────────────┤ 4. If match found:
 │ (hashed) │                                         │    - Check is_active
 └──────────┘                                         │    - Get tenant
      │                                               │    - Set request.tenant
      │ 5. Return plain key                           │
      │    ONCE to tenant                             │ 5. If no match:
      │    (never stored)                             │    Return 401 Unauthorized
      ▼                                               ▼
 ┌──────────┐                                    ┌──────────┐
 │  Tenant  │                                    │  View    │
 │  stores  │                                    │ proceeds │
 │  key     │                                    │ with     │
 │  securely│                                    │ request  │
 └──────────┘                                    └──────────┘
```

**Security measures:**
- Keys generated with `secrets.token_urlsafe(32)` (256-bit entropy)
- Keys hashed with PBKDF2-SHA256 (Django's password hasher)
- Plain key shown **only once** at creation
- Keys prefixed with `sk_live_` or `sk_test_` for easy identification

---

### 2. Tenant Isolation (Data Protection)

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                              TENANT ISOLATION FLOW                                  │
└─────────────────────────────────────────────────────────────────────────────────────┘

                       REQUEST FROM TENANT A
                       ════════════════════

  ┌────────────┐         ┌─────────────┐         ┌─────────────┐
  │  Tenant A  │────────▶│  Middleware │────────▶│    View     │
  │ X-API-KEY  │         │  sets       │         │  ALWAYS     │
  │ key_for_A  │         │ request.    │         │  filters by │
  └────────────┘         │ tenant = A  │         │ tenant=A    │
                         └─────────────┘         └──────┬──────┘
                                                        │
                                                        ▼
                               ┌────────────────────────────────────────┐
                               │              DATABASE                   │
                               │  ┌──────────────────────────────────┐  │
                               │  │         notifications            │  │
                               │  │  ┌────────┬─────────┬─────────┐  │  │
                               │  │  │   id   │ tenant  │   to    │  │  │
                               │  │  ├────────┼─────────┼─────────┤  │  │
                               │  │  │  n1    │    A    │ a@x.com │  │  │ ◄── Tenant A sees
                               │  │  │  n2    │    A    │ b@x.com │  │  │     only these
                               │  │  ├────────┼─────────┼─────────┤  │  │
                               │  │  │  n3    │    B    │ c@y.com │  │  │ ◄── Tenant B's data
                               │  │  │  n4    │    B    │ d@y.com │  │  │     INVISIBLE to A
                               │  │  └────────┴─────────┴─────────┘  │  │
                               │  └──────────────────────────────────┘  │
                               └────────────────────────────────────────┘

  ISOLATION RULES:
  ════════════════
  ✓ Every query MUST include tenant filter
  ✓ Notification.objects.filter(tenant=request.tenant)
  ✓ Template.objects.filter(tenant=request.tenant)
  ✓ Never expose tenant_id in public URLs
  ✓ Use notification UUID, not sequential IDs
```

**Security measures:**
- Middleware attaches `request.tenant` after authentication
- All QuerySets filtered by `tenant=request.tenant`
- UUIDs used instead of sequential IDs (prevents enumeration attacks)
- Cross-tenant access impossible at database query level

---

### 3. Notification Send Flow

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                           SECURE NOTIFICATION FLOW                                  │
└─────────────────────────────────────────────────────────────────────────────────────┘

   TENANT                     DJANGO                      CELERY                PROVIDER
     │                          │                           │                      │
     │  POST /v1/notify         │                           │                      │
     │  X-API-KEY: sk_xxx       │                           │                      │
     │  {                       │                           │                      │
     │    "channel": "email",   │                           │                      │
     │    "to": "user@x.com",   │                           │                      │
     │    "template": "otp",    │                           │                      │
     │    "data": {"code":123}  │                           │                      │
     │  }                       │                           │                      │
     │ ────────────────────────▶│                           │                      │
     │                          │                           │                      │
     │                     1. VALIDATE                      │                      │
     │                     ══════════                       │                      │
     │                     - Auth middleware                │                      │
     │                     - Check tenant active            │                      │
     │                     - Validate input schema          │                      │
     │                     - Sanitize 'to' address          │                      │
     │                     - Check template exists          │                      │
     │                     - Check template belongs         │                      │
     │                       to this tenant                 │                      │
     │                          │                           │                      │
     │                     2. CREATE RECORD                 │                      │
     │                     ════════════════                 │                      │
     │                     - Notification(                  │                      │
     │                         tenant=request.tenant,       │                      │
     │                         status="pending",            │                      │
     │                         ...                          │                      │
     │                       )                              │                      │
     │                          │                           │                      │
     │                     3. QUEUE TASK                    │                      │
     │                     ═════════════                    │                      │
     │                          │ send_notification.delay   │                      │
     │                          │ (notification_id)         │                      │
     │                          │ ─────────────────────────▶│                      │
     │                          │                           │                      │
     │  {"id": "uuid-xxx",      │                           │                      │
     │   "status": "pending"}   │                           │                      │
     │ ◀────────────────────────│                           │                      │
     │                          │                      4. PROCESS                  │
     │                          │                      ══════════                  │
     │                          │                      - Fetch notification        │
     │                          │                      - Render template           │
     │                          │                      - Select provider           │
     │                          │                           │                      │
     │                          │                      5. SEND                     │
     │                          │                      ══════                      │
     │                          │                           │  API call            │
     │                          │                           │ ─────────────────────▶│
     │                          │                           │                      │
     │                          │                           │  Response            │
     │                          │                           │ ◀─────────────────────│
     │                          │                           │                      │
     │                          │                      6. UPDATE STATUS            │
     │                          │                      ════════════════            │
     │                          │                      - status="sent"             │
     │                          │                      - provider_response={...}   │
     │                          │                      - sent_at=now()             │
     │                          │                           │                      │
     │                          │                      7. ON FAILURE               │
     │                          │                      ═════════════               │
     │                          │                      - Retry with backoff        │
     │                          │                      - Max 3 retries             │
     │                          │                      - Move to DeadLetter        │
```

---

### 4. Security Checklist

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                              SECURITY MEASURES                                      │
└─────────────────────────────────────────────────────────────────────────────────────┘

 AUTHENTICATION & AUTHORIZATION
 ══════════════════════════════
 ✓ API keys hashed with PBKDF2 (not plain text)
 ✓ Keys generated with cryptographic randomness
 ✓ Keys can be deactivated without deletion
 ✓ Tenant must be active to use API
 ✓ All endpoints require valid API key

 DATA PROTECTION
 ════════════════
 ✓ Tenant isolation at query level
 ✓ UUIDs prevent ID enumeration
 ✓ PII (emails, phones) not logged in plain text
 ✓ Provider credentials in env vars, not code
 ✓ HTTPS enforced (nginx/load balancer level)

 INPUT VALIDATION
 ════════════════
 ✓ DRF serializers validate all input
 ✓ Email addresses validated format
 ✓ Phone numbers validated format
 ✓ Template variables sanitized
 ✓ JSON schema validation for data field

 RATE LIMITING
 ═════════════
 ✓ Per-tenant rate limits
 ✓ Prevent abuse/spam
 ✓ Protect provider accounts from overuse

 AUDIT & MONITORING
 ══════════════════
 ✓ Every notification logged with tenant
 ✓ API key last_used_at tracked
 ✓ Error messages stored for debugging
 ✓ Provider responses stored for audit

 SECRETS MANAGEMENT
 ══════════════════
 ✓ Django SECRET_KEY in .env
 ✓ DB credentials in .env
 ✓ Provider API keys in .env
 ✓ .env in .gitignore (never committed)
```

---

## Implementation Checklist

### Phase 1: Core API & Security (Critical)

| # | Task | Status |
|---|------|--------|
| 1 | Create Django models | ✅ Done |
| 2 | Run migrations | ✅ Done |
| 3 | Register models in admin | ✅ Done |
| 4 | API Key generation endpoint | ⬜ Pending |
| 5 | API Key authentication middleware | ⬜ Pending |
| 6 | Tenant isolation middleware | ⬜ Pending |
| 7 | NotifyView + serializer | ⬜ Pending |
| 8 | URL routing | ⬜ Pending |

### Phase 2: Async Processing

| # | Task | Status |
|---|------|--------|
| 9 | Celery task for sending notifications | ⬜ Pending |
| 10 | Provider adapters (Email/SMS) | ⬜ Pending |
| 11 | Retry logic with exponential backoff | ⬜ Pending |
| 12 | Dead letter queue handling | ⬜ Pending |

### Phase 3: CRUD & Management

| # | Task | Status |
|---|------|--------|
| 13 | Template CRUD endpoints | ⬜ Pending |
| 14 | Notification logs endpoint | ⬜ Pending |
| 15 | Tenant registration | ⬜ Pending |
| 16 | Rate limiting | ⬜ Pending |

---

## Getting Started

### Prerequisites

- Python 3.12+
- PostgreSQL 14+
- Redis 6+

### Installation

```bash
# Clone the repository
git clone <repository-url>
cd smart-notification-service

# Install dependencies with Poetry
poetry install

# Copy environment file
cp .env.example .env
# Edit .env with your configuration

# Run migrations
poetry run python manage.py migrate

# Create superuser
poetry run python manage.py createsuperuser

# Start development server
poetry run python manage.py runserver

# Start Celery worker (in another terminal)
poetry run celery -A core worker -l info
```

### Environment Variables

```bash
# .env file
DJANGO_SECRET_KEY=your-secret-key
DEBUG=True
ALLOWED_HOSTS=127.0.0.1,localhost

# Database
DB_NAME=notification_service
DB_USER=notification_user
DB_PASSWORD=your-password
DB_HOST=127.0.0.1
DB_PORT=5432

# Redis
REDIS_URL=redis://127.0.0.1:6379/0

# Email (SMTP/SES)
EMAIL_HOST=smtp.example.com
EMAIL_PORT=587
EMAIL_HOST_USER=your-email
EMAIL_HOST_PASSWORD=your-password
EMAIL_USE_TLS=True

# Provider Keys (add as needed)
TWILIO_ACCOUNT_SID=your-sid
TWILIO_AUTH_TOKEN=your-token
TWILIO_FROM_NUMBER=+1234567890
```

---

## API Reference

### Authentication

All API requests require the `X-API-KEY` header:

```bash
curl -X POST https://api.example.com/v1/notify \
  -H "X-API-KEY: sk_live_abc123..." \
  -H "Content-Type: application/json" \
  -d '{"channel": "email", "to": "user@example.com", ...}'
```

### Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/v1/notify` | Send a notification |
| GET | `/v1/notifications` | List notifications |
| GET | `/v1/notifications/{id}` | Get notification details |
| POST | `/v1/templates` | Create a template |
| GET | `/v1/templates` | List templates |
| GET | `/v1/templates/{id}` | Get template details |
| PUT | `/v1/templates/{id}` | Update a template |
| DELETE | `/v1/templates/{id}` | Delete a template |

### Send Notification

**Request:**
```json
POST /v1/notify
{
  "channel": "email",
  "to": "user@example.com",
  "template": "welcome_email",
  "data": {
    "name": "John Doe",
    "company": "Acme Corp"
  }
}
```

**Response:**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "pending",
  "channel": "email",
  "to": "user@example.com",
  "created_at": "2024-01-15T10:30:00Z"
}
```

### Status Codes

| Code | Description |
|------|-------------|
| 200 | Success |
| 201 | Created |
| 400 | Bad Request (validation error) |
| 401 | Unauthorized (invalid/missing API key) |
| 403 | Forbidden (tenant inactive) |
| 404 | Not Found |
| 429 | Too Many Requests (rate limited) |
| 500 | Internal Server Error |

---

## Project Structure

```
smart-notification-service/
├── core/                      # Django project settings
│   ├── __init__.py
│   ├── celery.py              # Celery configuration
│   ├── settings.py            # Django settings
│   ├── urls.py                # URL routing
│   └── wsgi.py
├── tenants/                   # Tenant management app
│   ├── models.py              # BusinessTenant, APIKey
│   ├── middleware.py          # Auth + tenant isolation
│   ├── services.py            # Key generation service
│   ├── views.py               # API views
│   └── admin.py
├── notifications/             # Notification handling app
│   ├── models.py              # Template, Notification, DeadLetter
│   ├── serializers.py         # DRF serializers
│   ├── views.py               # NotifyView, TemplateViewSet
│   ├── tasks.py               # Celery tasks
│   ├── providers/             # Provider adapters
│   │   ├── base.py
│   │   ├── email_provider.py
│   │   ├── sms_provider.py
│   │   └── push_provider.py
│   └── admin.py
├── core_utils/                # Shared utilities
├── manage.py
├── pyproject.toml             # Poetry dependencies
├── poetry.lock
└── README.md
```

---

## License

Private - All rights reserved.

---

## User Flows & APIs

### 1. Tenant onboarding & API key

- **Goal**: A new customer (tenant) signs up and obtains an API key.
- **Steps & APIs**:
  - **Register tenant**
    - **API**: `POST /v1/tenants/register/`
    - **Auth**: none
    - **Body**:
      - `name`, `email`
    - **Result**: Creates a `BusinessTenant` and returns:
      - `tenant` object (with `tenant_id`)
      - **initial API key** (plain `api_key.key` – shown only once)
  - **Get current tenant profile**
    - **API**: `GET /v1/tenants/me/`
    - **Auth**: `X-API-KEY`
    - **Use**: Dashboard shows tenant name, status, etc.
  - **Manage API keys**
    - **List keys**:
      - **API**: `GET /v1/api-keys/`
      - **Auth**: `X-API-KEY`
    - **Create new key**:
      - **API**: `POST /v1/api-keys/`
      - **Body**: `{ "name": "My server key", "is_test": false }`
      - **Result**: New key + plain value (only once)
    - **Deactivate key**:
      - **API**: `POST /v1/api-keys/{id}/deactivate/`
      - **Auth**: `X-API-KEY` of another active key

### 2. Template management

- **Goal**: Tenant defines reusable content for emails/SMS/etc.
- **APIs (all require `X-API-KEY`)**:
  - **Create template**
    - `POST /v1/templates/`
    - Body example:
      - `{"name":"welcome_email","channel":"email","subject":"Welcome, {{name}}","body":"Hi {{name}}, welcome to {{company}}!","variables":{"name":"string","company":"string"},"is_active":true}`
  - **List templates**
    - `GET /v1/templates/`
    - Returns all templates for `request.tenant`.
  - **Retrieve single template**
    - `GET /v1/templates/{id}/`
  - **Update template**
    - `PUT /v1/templates/{id}/`
  - **Delete template**
    - `DELETE /v1/templates/{id}/`
  - **Preview template rendering**
    - `POST /v1/templates/{id}/preview/`
    - Body: `{ "data": { "name": "John", "company": "Acme" } }`
    - Result: Rendered `subject` and `body` (without sending).

### 3. Sending notifications using templates

- **Goal**: Tenant triggers notifications through the unified API.
- **API**: `POST /v1/notify/`
- **Auth**: `X-API-KEY`
- **Body (template-based)**:
  - `channel`: `"email" | "sms" | "whatsapp" | "push"`
  - `to`: recipient (email address, phone, device token)
  - `template`: template name (e.g., `"welcome_email"`) or
  - `template_id`: numeric id
  - `data`: JSON variables for the template (e.g., `{ "name": "John", "company": "Acme" }`)
- **Flow**:
  1. Middleware authenticates API key and sets `request.tenant`.
  2. View validates payload and resolves template for that tenant.
  3. Creates a `Notification` row with `status = "pending"`.
  4. Enqueues `send_notification_task` to Celery via Redis.
  5. Returns `202 Accepted` with the notification `id` and `status: "pending"`.

### 4. Sending notifications with inline content (no template)

- **API**: `POST /v1/notify/`
- **Auth**: `X-API-KEY`
- **Body (inline)**:
  - `channel`, `to`, `data`
  - `subject` and `body` provided directly instead of `template`/`template_id`.
- **Flow**:
  - Same as template-based send, but `_render_notification` uses the inline `subject`/`body` and Jinja2 + `data` to render content.

### 5. Tracking notification status

- **List notifications for a tenant**
  - **API**: `GET /v1/notifications/`
  - **Query params**:
    - `status` (optional): `pending|processing|sent|failed|delivered`
    - `channel` (optional): `email|sms|whatsapp|push`
    - `limit` (optional): default `100`
  - **Use case**: Dashboard “activity feed” or admin view.
- **Get single notification**
  - **API**: `GET /v1/notifications/{id}/`
  - **Use case**: Show details page, including `provider_response` and `error_message` (if any).

### 6. Investigating failures (Dead Letter Queue)

- **Goal**: See notifications that permanently failed after all retries.
- **API**: `GET /v1/dead-letters/`
- **Auth**: `X-API-KEY`
- **Result**: List of `DeadLetter` entries, including:
  - `notification_id`, `notification_channel`, `notification_to`
  - `reason` (what went wrong)
  - `retry_count`, `created_at`
- **Typical flow**:
  - Support/ops checks this endpoint or a dashboard backed by it.
  - Manually fix configuration (bad email, misconfigured provider, etc.).
  - Optionally, re-trigger a new notification via `/v1/notify/`.

