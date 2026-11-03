# DaanGives Backend — Digital Donor & Beneficiary Platform

An integrated, enterprise-grade backend platform built with Django and Django REST Framework for transparent philanthropic giving, NGO governance, CSR partnership facilitation, field distribution verification, automated Form 10BD/10BE tax compliance, and citizen grievance redressal.

---

## Architecture Overview

```
                      [ Client Applications ]
                     (React Web / Mobile / API)
                                 │
                                 ▼ (REST API / JWT Auth)
┌────────────────────────────────────────────────────────────────────────┐
│                          DaanGives Backend                             │
│                                                                        │
│   ┌──────────────┐   ┌──────────────┐   ┌──────────────────────────┐   │
│   │    users     │   │     ngo      │   │        campaigns         │   │
│   │  Auth & RBAC │   │ Darpan & Doc │   │ Milestones, Proofs, 10BD │   │
│   └──────────────┘   └──────────────┘   └──────────────────────────┘   │
│   ┌──────────────┐   ┌──────────────┐   ┌──────────────────────────┐   │
│   │     csr      │   │  grievances  │   │        analytics         │   │
│   │ Partnerships │   │ SLA Workflow │   │  Intelligence Dashboard  │   │
│   └──────────────┘   └──────────────┘   └──────────────────────────┘   │
└────────────────────────────────────────────────────────────────────────┘
                                 │
                 ┌───────────────┴───────────────┐
                 ▼                               ▼
       [ PostgreSQL Database ]        [ External Integrations ]
        (37 Public Tables)             • Razorpay Gateway
                                       • Transactional SMTP (SES)
                                       • ReportLab PDF Engine
```

### Core Modules:
- **`users`**: Custom user model with multi-role RBAC (`DONOR`, `NGO`, `ADMIN`, `COMPANY`), JWT auth, avatar management, and password recovery.
- **`ngo`**: NGO onboarding verification, Darpan ID validation, 12A/80G status, leadership rosters, document vault, and bank account compliance.
- **`campaigns`**: Public and verified campaigns, phased milestone disbursement, geotagged distribution proof tracking, Razorpay payment capture, cryptographic receipt generation, and Section 80G Form 10BD/10BE compliance reporting.
- **`csr`**: Corporate Social Responsibility marketplace, corporate preferences, requirement builder, MoUs, and partnership governance.
- **`grievances`**: Multi-stakeholder ticketing, role-scoped transitions, SLA breach monitoring, audit history, and email notifications.
- **`analytics`**: Platform-wide and role-scoped intelligence dashboards (KPIs, disbursement trends, regional distribution).

---

## System Requirements

- **Python**: 3.11+ (tested on Python 3.14)
- **Database**: PostgreSQL 14+ (or 16+)
- **OS**: macOS, Linux, or Windows (WSL)

---

## Installation & Setup

### 1. Clone & Navigate to Backend
```bash
cd daangives-backend
```

### 2. Create and Activate Virtual Environment
```bash
python3 -m venv env_daan
source env_daan/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables
Copy the template configuration file:
```bash
cp .env.example .env
```
Edit `.env` with your local or production credentials (see configuration section below).

### 5. Apply Database Migrations
```bash
python manage.py migrate
```

### 6. Run System Health Checks
```bash
python manage.py check
```

### 7. Run the Development Server
```bash
python manage.py runserver 0.0.0.0:8000
```
The REST API will be available at `http://localhost:8000/api/v1/`.

---

## Environment Variables

| Variable | Description | Default / Example |
| :--- | :--- | :--- |
| `SECRET_KEY` | Django cryptographic signing secret | Generate via `secrets.token_urlsafe(50)` |
| `DEBUG` | Enable/disable debug mode (`True`/`False`) | `True` (dev), `False` (prod) |
| `ALLOWED_HOSTS` | Comma-separated allowed hostnames | `localhost,127.0.0.1,api.daangives.org` |
| `DB_ENGINE` | Database engine backend | `django.db.backends.postgresql` |
| `DB_NAME` | PostgreSQL database name | `daangives_db` |
| `DB_USER` | PostgreSQL username | `daan_user` |
| `DB_PASSWORD` | PostgreSQL password | `YOUR_DATABASE_PASSWORD` |
| `DB_HOST` | PostgreSQL host | `127.0.0.1` |
| `DB_PORT` | PostgreSQL port | `5432` |
| `CORS_ALLOWED_ORIGINS` | Comma-separated allowed CORS origins | `http://localhost:5173,https://daangives.org` |
| `CSRF_TRUSTED_ORIGINS` | Comma-separated CSRF trusted origins | `http://localhost:5173,https://daangives.org` |
| `RAZORPAY_KEY_ID` | Razorpay Key ID (`rzp_test_*` or `rzp_live_*`) | `YOUR_RAZORPAY_KEY_ID` |
| `RAZORPAY_KEY_SECRET` | Razorpay Key Secret | `YOUR_RAZORPAY_KEY_SECRET` |
| `RAZORPAY_WEBHOOK_SECRET` | Webhook verification secret | `YOUR_RAZORPAY_WEBHOOK_SECRET` |
| `EMAIL_BACKEND` | Email delivery backend | `django.core.mail.backends.console.EmailBackend` |
| `EMAIL_HOST` | SMTP server host | `smtp.sendgrid.net` or `email-smtp.us-east-1.amazonaws.com` |
| `EMAIL_PORT` | SMTP port | `587` |
| `EMAIL_HOST_USER` | SMTP username | `YOUR_SMTP_USERNAME` |
| `EMAIL_HOST_PASSWORD` | SMTP password / API token | `YOUR_SMTP_PASSWORD` |
| `EMAIL_USE_TLS` | Enable TLS for SMTP | `True` |
| `DEFAULT_FROM_EMAIL` | Default sender email header | `DaanGives Platform <noreply@daangives.org>` |
| `SECURE_SSL_REDIRECT` | Redirect HTTP to HTTPS | `False` (dev), `True` (prod) |
| `SESSION_COOKIE_SECURE` | Send session cookie over HTTPS only | `False` (dev), `True` (prod) |
| `CSRF_COOKIE_SECURE` | Send CSRF cookie over HTTPS only | `False` (dev), `True` (prod) |
| `SECURE_HSTS_SECONDS` | HTTP Strict Transport Security duration | `0` (dev), `31536000` (prod) |

---

## Testing & Quality Assurance

Run the comprehensive automated test suite (1,571+ unit and integration tests):
```bash
python manage.py test --keepdb --noinput
```

Verify migration status:
```bash
python manage.py makemigrations --check --dry-run
```

---

## Production Security Notes

1. **Secret Key**: In production, `SECRET_KEY` is strictly required. Django will refuse to start if it is missing and `DEBUG=False`.
2. **Payment Gateway**: Never hard-code Razorpay keys in source code. Use sandbox keys (`rzp_test_*`) for testing and restricted environment variables for production (`rzp_live_*`).
3. **Protected Records**: Monetary donation records and generated 80G tax receipt records are protected with SHA-256 hashes for non-repudiation.
4. **HTTPS Enforced**: When deploying behind a reverse proxy (e.g., Nginx, AWS ALB), set `SECURE_SSL_REDIRECT=True` and configure `CSRF_TRUSTED_ORIGINS`.
