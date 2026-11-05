from pathlib import Path

import environ
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parents[1]
ROOT_DIR = BASE_DIR.parents[1]
env = environ.Env(DJANGO_DEBUG=(bool, False))
environ.Env.read_env(ROOT_DIR / ".env", overwrite=False)

SECRET_KEY = env("DJANGO_SECRET_KEY")
if SECRET_KEY.startswith("replace-"):
    raise ImproperlyConfigured("请运行 scripts/init_dev.py 生成本地凭据。")
DEBUG = env("DJANGO_DEBUG")
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1", "[::1]"])
CSRF_TRUSTED_ORIGINS = env.list(
    "DJANGO_CSRF_TRUSTED_ORIGINS",
    default=["http://localhost:5173", "http://127.0.0.1:5173"] if DEBUG else [],
)
INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "rest_framework",
    "core",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
]
ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("POSTGRES_DB", default="paper_assistant"),
        "USER": env("POSTGRES_USER", default="paper"),
        "PASSWORD": env("POSTGRES_PASSWORD"),
        "HOST": env("POSTGRES_HOST", default="127.0.0.1"),
        "PORT": env.int("POSTGRES_PORT", default=5432),
        "OPTIONS": {"connect_timeout": 3},
    }
}
LANGUAGE_CODE = "zh-hans"
TIME_ZONE = "Asia/Shanghai"
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
REST_FRAMEWORK = {
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
        "core.wechat_auth.WechatAuthentication",
    ],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
}
NEO4J_URI = env("NEO4J_URI", default="bolt://127.0.0.1:7687")
NEO4J_USER = env("NEO4J_USER", default="neo4j")
NEO4J_PASSWORD = env("NEO4J_PASSWORD")
S3_ENDPOINT_URL = env("S3_ENDPOINT_URL", default="http://127.0.0.1:8333")
S3_ACCESS_KEY = env("S3_ACCESS_KEY")
S3_SECRET_KEY = env("S3_SECRET_KEY")
S3_REGION = env("S3_REGION", default="us-east-1")
REDIS_URL = env("REDIS_URL", default="redis://127.0.0.1:6379/0")
CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_TRACK_STARTED = True
CELERY_RESULT_EXPIRES = 3600
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_BROKER_CONNECTION_TIMEOUT = 3
CELERY_BROKER_TRANSPORT_OPTIONS = {"socket_connect_timeout": 3, "socket_timeout": 3}
CELERY_REDIS_SOCKET_CONNECT_TIMEOUT = 3
CELERY_REDIS_SOCKET_TIMEOUT = 3
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SECURE_CONTENT_TYPE_NOSNIFF = True

CELERY_BEAT_SCHEDULE = {"recover-jobs": {"task": "jobs.recover", "schedule": 15.0}}

WECHAT_APP_ID = env("WECHAT_APP_ID", default="")
WECHAT_APP_SECRET = env("WECHAT_APP_SECRET", default="")

MATERIAL_BUCKET = env("MATERIAL_BUCKET", default="paper-materials")
FILE_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 21 * 1024 * 1024

DATA_UPLOAD_MAX_NUMBER_FILES = 1
