from mainpage.settings import *

DEBUG = os.environ.get("DJANGO_DEBUG", "").lower() == "true"
ENVIRONMENT = None

# Don't use the dev key, fail if unsepcified
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")

# use captcha in production only
USE_CAPTCHA = os.environ.get("USE_CAPTCHA", str(not DEBUG)).lower() == "true"

VITE_FORCE_DEV = False
# configure host name + dependencies
HOST_NAME = os.environ["HOST_NAME"]
if DEBUG is True:
    ALLOWED_HOSTS = ["*"]
else:
    ALLOWED_HOSTS = [HOST_NAME]

CSRF_TRUSTED_ORIGINS = [
    f"http://{HOST_NAME}",
    f"https://{HOST_NAME}",
]

INSTALLED_APPS += [
    "django_guid",
]

MIDDLEWARE = [
    "django_guid.middleware.guid_middleware",
] + MIDDLEWARE

DJANGO_GUID = {
    "GUID_HEADER_NAME": "X-Request-Id",
    "VALIDATE_GUID": False,
    "RETURN_HEADER": False,
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "correlation_id": {
            "()": "django_guid.log_filters.CorrelationId",
            "correlation_id_field": "http.request.id",
        },
        "request_context": {"()": "mainpage.log_filters.AddRequestContext"},
    },
    "formatters": {
        "ecs": {"()": "ecs_logging.StdlibFormatter"},
    },
    "handlers": {
        "console": {
            "formatter": "ecs",
            "class": "logging.StreamHandler",
            "filters": ["correlation_id"],
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "DEBUG",
    },
    "loggers": {
        "mainpage": {
            "handlers": ["console"],
            "propagate": False,
            "level": "DEBUG",
        },
        "django.request": {
            "filters": ["request_context"],
        },
        "django.db.backends": {
            "handlers": ["console"],
            "level": "DEBUG" if "SHOW_SQL" in os.environ else "INFO",
            "propagate": False,
        },
        "django_guid": {
            "level": "WARNING",
        },
    },
}
