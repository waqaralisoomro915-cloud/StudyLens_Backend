from .base import *

DATABASES = {"default": dj_database_url.config(env="TEST_DATABASE_URL", default="sqlite:///:memory:")}
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
CELERY_TASK_ALWAYS_EAGER = True
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
