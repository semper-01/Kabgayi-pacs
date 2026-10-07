"""
Django settings for the Kabgayi Level 2 Teaching Hospital PACS backend.

Phase 2 scope: establish a clean backend foundation only.
Architectural principle: Orthanc owns DICOM/PACS responsibilities, Django owns
application/business logic, PostgreSQL owns application data, and the React UI
will be added in a later phase. No DICOM data is stored in Django.

All secrets and credentials are supplied through the environment. A local,
git-ignored ``.env`` file (see ``.env.example``) is loaded for development.
"""
import os
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

# Build paths inside the project like this: BASE_DIR / "subdir".
BASE_DIR = Path(__file__).resolve().parent.parent

# Load development environment variables from backend/.env (git-ignored).
load_dotenv(BASE_DIR / ".env")

# ---------------------------------------------------------------------------
# Core security settings (from environment)
# ---------------------------------------------------------------------------
SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]

DEBUG = os.environ.get("DJANGO_DEBUG", "False").lower() in {
    "1",
    "true",
    "yes",
    "on",
}

ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    if host.strip()
]

# ---------------------------------------------------------------------------
# Application definition
# ---------------------------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party
    "rest_framework",
    # Project applications
    "core",
    "studies",
    "audit",
    "configuration",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# ---------------------------------------------------------------------------
# Database — PostgreSQL (Django owns application data)
# ---------------------------------------------------------------------------
# Credentials are read from the environment; no passwords are committed.
# Prefer DATABASE_URL (e.g. postgres://user:password@host:port/db) but allow a
# decomposed set of POSTGRES_* variables as an alternative.
DATABASE_URL = os.environ.get("DATABASE_URL")

if DATABASE_URL:
    DATABASES = {
        "default": dj_database_url.parse(
            DATABASE_URL,
            conn_max_age=60,
        )
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get("POSTGRES_DB", "kabgayi_pacs"),
            "USER": os.environ.get("POSTGRES_USER", "kabgayi_pacs"),
            "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
            "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
            "PORT": os.environ.get("POSTGRES_PORT", "5432"),
            "CONN_MAX_AGE": 60,
        }
    }

# ---------------------------------------------------------------------------
# Authentication — Authentication V1
# ---------------------------------------------------------------------------
# Community vs. administrator accounts only (deferred to V2 for individual
# user accountability). Custom user established before the first migration.
AUTH_USER_MODEL = "core.User"

# ---------------------------------------------------------------------------
# Password validation
# ---------------------------------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

# ---------------------------------------------------------------------------
# Internationalization
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "en-us"

TIME_ZONE = "Africa/Kigali"

USE_I18N = True

USE_TZ = True

# ---------------------------------------------------------------------------
# Static files (CSS, JavaScript, Images)
# ---------------------------------------------------------------------------
STATIC_URL = "static/"

# ---------------------------------------------------------------------------
# Default primary key field type
# ---------------------------------------------------------------------------
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# Django REST Framework
# ---------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
}

# ---------------------------------------------------------------------------
# External service — Orthanc (DICOM/PACS source of truth)
# ---------------------------------------------------------------------------
# Django talks to the Orthanc REST API (never directly to Orthanc storage).
# Credentials are read from the environment; nothing is hard-coded here. If the
# configured Orthanc development instance requires no authentication, leave
# ORTHANC_USERNAME/ORTHANC_PASSWORD empty and no Authorization header is sent.
ORTHANC_URL = os.environ.get("ORTHANC_URL", "http://localhost:8042").rstrip("/")
ORTHANC_USERNAME = os.environ.get("ORTHANC_USERNAME", "")
ORTHANC_PASSWORD = os.environ.get("ORTHANC_PASSWORD", "")
ORTHANC_TIMEOUT = float(os.environ.get("ORTHANC_TIMEOUT", "10"))