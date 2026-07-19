from pathlib import Path
from datetime import timedelta
from decouple import config, Csv
from celery.schedules import crontab
from corsheaders.defaults import default_headers

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = config("SECRET_KEY", default="dev-fasoim-change-me")
DEBUG = config("DEBUG", default=True, cast=bool)
ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="127.0.0.1,localhost", cast=Csv())

# Frontends autorisés à appeler l'API depuis un navigateur.
CORS_ALLOWED_ORIGINS = config(
    "CORS_ALLOWED_ORIGINS",
    default="http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173,http://127.0.0.1:4173",
    cast=Csv(),
)
CORS_URLS_REGEX = r"^/api/.*$"

CORS_ALLOW_HEADERS = (
    *default_headers,
    "x-fasoim-affectation",
)

INSTALLED_APPS = [
    # Django
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    # API
    "rest_framework",
    "rest_framework_simplejwt",
    "drf_spectacular",
    "corsheaders",

     # Applications FasoIM
    "accounts",
    "sessions_app",
    "imports_app",
    "immerges",
    "affectations",
    "organisation",
    "activites",
    "sante",
    "kits",
    "repas",
    "incidents",
    "documents",
    "notifications",
    "audit",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "accounts.middleware.AffectationCouranteMiddleware",
    "audit.service.AuditMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
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

DB_ENGINE = config("DB_ENGINE", default="sqlite")

if DB_ENGINE == "postgresql":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": config("DB_NAME"),
            "USER": config("DB_USER"),
            "PASSWORD": config("DB_PASSWORD"),
            "HOST": config("DB_HOST", default="localhost"),
            "PORT": config("DB_PORT", default="5432"),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / config("DB_NAME", default="db.sqlite3"),
        }
    }

LANGUAGE_CODE = "fr-fr"
TIME_ZONE = "Africa/Ouagadougou"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_USER_MODEL = "accounts.Acteur"

REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
    ),
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=60),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "AUTH_HEADER_TYPES": ("Bearer",),
}

SPECTACULAR_SETTINGS = {
    "TITLE": "API FasoIM",
    "DESCRIPTION": "API backend de la plateforme FasoIM - gestion de l’immersion patriotique.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}


# Cache Redis
REDIS_CACHE_URL = config("REDIS_CACHE_URL", default="redis://127.0.0.1:6379/1")

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": REDIS_CACHE_URL,
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
        },
    }
}

# Celery / Redis
CELERY_BROKER_URL = config("CELERY_BROKER_URL", default="redis://127.0.0.1:6379/0")
CELERY_RESULT_BACKEND = config("CELERY_RESULT_BACKEND", default=CELERY_BROKER_URL)
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE
CELERY_ENABLE_UTC = True
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = config("CELERY_TASK_TIME_LIMIT", default=1800, cast=int)

# Email / SMTP
EMAIL_BACKEND = config("EMAIL_BACKEND", default="django.core.mail.backends.smtp.EmailBackend")
EMAIL_HOST = config("EMAIL_HOST", default="localhost")
EMAIL_PORT = config("EMAIL_PORT", default=587, cast=int)
EMAIL_USE_TLS = config("EMAIL_USE_TLS", default=True, cast=bool)
EMAIL_HOST_USER = config("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = config("EMAIL_HOST_PASSWORD", default="")
DEFAULT_FROM_EMAIL = config("DEFAULT_FROM_EMAIL", default="FasoIM <noreply@fasoim.local>")
EMAIL_TIMEOUT = config("EMAIL_TIMEOUT", default=20, cast=int)

# Notifications sans table : e-mails, idempotence Redis + preuve dans audit.
NOTIFICATIONS_ENABLED = config("NOTIFICATIONS_ENABLED", default=True, cast=bool)
NOTIFICATIONS_ENABLE_DURING_TESTS = config("NOTIFICATIONS_ENABLE_DURING_TESTS", default=False, cast=bool)
NOTIFICATIONS_LOCK_SECONDS = config("NOTIFICATIONS_LOCK_SECONDS", default=300, cast=int)
NOTIFICATIONS_TENTATIVE_TTL_SECONDS = config(
    "NOTIFICATIONS_TENTATIVE_TTL_SECONDS", default=600, cast=int
)
NOTIFICATIONS_DEDUP_SUCCESS_SECONDS = config(
    "NOTIFICATIONS_DEDUP_SUCCESS_SECONDS", default=31536000, cast=int
)
NOTIFICATIONS_BATCH_SIZE = config("NOTIFICATIONS_BATCH_SIZE", default=200, cast=int)
NOTIFICATIONS_MAX_RELAIS_ETABLISSEMENT = config(
    "NOTIFICATIONS_MAX_RELAIS_ETABLISSEMENT", default=3, cast=int
)
NOTIFICATIONS_RETRY_DELAY_SECONDS = config(
    "NOTIFICATIONS_RETRY_DELAY_SECONDS", default=60, cast=int
)
FASOIM_LOGIN_URL = config("FASOIM_LOGIN_URL", default="http://localhost:5173/espace-acteur")
FASOIM_PUBLIC_URL = config("FASOIM_PUBLIC_URL", default="http://localhost:5173")

# Documents, attestations et publications officielles.
DOCUMENTS_PUBLIC_RATE_LIMIT = config("DOCUMENTS_PUBLIC_RATE_LIMIT", default=20, cast=int)
DOCUMENTS_PUBLIC_RATE_WINDOW_SECONDS = config("DOCUMENTS_PUBLIC_RATE_WINDOW_SECONDS", default=900, cast=int)
DOCUMENTS_PROGRESS_TTL_SECONDS = config("DOCUMENTS_PROGRESS_TTL_SECONDS", default=86400, cast=int)
DOCUMENTS_DETECTION_READY_MINUTES = config("DOCUMENTS_DETECTION_READY_MINUTES", default=10, cast=int)
FASOIM_ATTESTATION_ARMOIRIES_PATH = config(
    "FASOIM_ATTESTATION_ARMOIRIES_PATH", default=""
)
FASOIM_ATTESTATION_LOGO_PATH = config(
    "FASOIM_ATTESTATION_LOGO_PATH", default=""
)

# Surveillance automatique des alertes et incidents
# Celery Beat doit être lancé séparément. Les tâches restent sans effet sur les
# validations métier : elles observent uniquement l'état persistant du système.
INCIDENTS_TAILLE_LOT_SCAN = config(
    "INCIDENTS_TAILLE_LOT_SCAN",
    default=500,
    cast=int,
)
INCIDENTS_MAX_ALERTES_CREEES_PAR_REGLE = config(
    "INCIDENTS_MAX_ALERTES_CREEES_PAR_REGLE",
    default=500,
    cast=int,
)
INCIDENTS_SCAN_LOCK_SECONDS = config(
    "INCIDENTS_SCAN_LOCK_SECONDS",
    default=CELERY_TASK_TIME_LIMIT + 300,
    cast=int,
)
INCIDENTS_SCAN_DEBOUNCE_SECONDS = config(
    "INCIDENTS_SCAN_DEBOUNCE_SECONDS",
    default=30,
    cast=int,
)
INCIDENTS_CONTROLES_CIBLES_ACTIFS = config(
    "INCIDENTS_CONTROLES_CIBLES_ACTIFS",
    default=True,
    cast=bool,
)

CELERY_BEAT_SCHEDULE = {
    "incidents-scan-integrite-toutes-les-5-minutes": {
        "task": "incidents.scanner_integrite_global",
        "schedule": crontab(minute="*/5"),
    },
    "incidents-escalade-toutes-les-5-minutes": {
        "task": "incidents.escalader_retards",
        "schedule": crontab(minute="*/5"),
    },
    "documents-detecter-centres-prets-attestations": {
        "task": "documents.detecter_centres_prets_attestations",
        "schedule": crontab(minute=f"*/{max(1, DOCUMENTS_DETECTION_READY_MINUTES)}"),
    },
}
