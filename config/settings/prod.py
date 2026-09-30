from .base import *

if SECRET_KEY.startswith("development-"):
    raise RuntimeError("Set a strong DJANGO_SECRET_KEY")
if not os.environ.get("DATABASE_URL", "").startswith("postgres"):
    raise RuntimeError("Production requires PostgreSQL")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_SSL_REDIRECT = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_HSTS_SECONDS = 31536000
SECURE_CONTENT_TYPE_NOSNIFF = True
