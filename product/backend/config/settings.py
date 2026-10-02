import os
import json
import secrets
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
REPO = BASE_DIR.parents[1]
DATA_DIR = Path(os.environ.get('SUPPLY_DATA_DIR', REPO / 'local/product-v1')).resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
os.chmod(DATA_DIR, 0o700)
secret_path = DATA_DIR / 'django.secret'
try:
    fd = os.open(secret_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
except FileExistsError:
    pass
else:
    with os.fdopen(fd, 'w') as stream:
        stream.write(secrets.token_urlsafe(64))
SECRET_KEY = secret_path.read_text().strip()
if len(SECRET_KEY) < 50:
    raise RuntimeError('Local secret is invalid')
DEBUG = False
ALLOWED_HOSTS = ['127.0.0.1', 'localhost', '[::1]']
if 'test' in sys.argv:
    ALLOWED_HOSTS.append('testserver')
ROOT_URLCONF = 'config.urls'
WSGI_APPLICATION = 'config.wsgi.application'
INSTALLED_APPS = ['django.contrib.auth', 'django.contrib.contenttypes', 'django.contrib.sessions', 'api']
MIDDLEWARE = [
    'api.middleware.BoundaryMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
]
DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': str(DATA_DIR / 'app.sqlite3'),
                         'OPTIONS': {'timeout': 20, 'transaction_mode': 'IMMEDIATE'}}}
database_config = DATA_DIR / 'database.json'
if database_config.exists() and os.environ.get('SUPPLY_SQLITE') != '1':
    if database_config.stat().st_mode & 0o077:
        raise RuntimeError('Database credentials must have mode 0600')
    config = json.loads(database_config.read_text())
    if set(config) != {'NAME', 'USER', 'PASSWORD', 'HOST', 'PORT'}:
        raise RuntimeError('Invalid PostgreSQL configuration')
    DATABASES = {'default': {'ENGINE': 'django.db.backends.postgresql', **config,
                            'CONN_MAX_AGE': 0, 'CONN_HEALTH_CHECKS': True,
                            'OPTIONS': {'pool': {'min_size': 1, 'max_size': 4, 'timeout': 10},
                                        'connect_timeout': 5}}}
AUTH_USER_MODEL = 'api.User'
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator', 'OPTIONS': {'user_attributes': ['email', 'name']}},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 15}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]
PASSWORD_HASHERS = ['django.contrib.auth.hashers.PBKDF2PasswordHasher']
SESSION_COOKIE_NAME = 'supply_session'
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_SECURE = os.environ.get('SUPPLY_HTTPS') == '1'
SESSION_COOKIE_AGE = 60 * 60 * 12
CSRF_COOKIE_NAME = 'supply_csrf'
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE
CSRF_FAILURE_VIEW = 'api.views.csrf_failure'
DATA_UPLOAD_MAX_MEMORY_SIZE = 24 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 1024 * 1024
DATA_UPLOAD_MAX_NUMBER_FIELDS = 20
DATA_UPLOAD_MAX_NUMBER_FILES = 2
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'same-origin'
LANGUAGE_CODE = 'ru'
TIME_ZONE = 'Europe/Moscow'
USE_TZ = True
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
FRONTEND_DIST = REPO / 'product/frontend/dist'
LOGGING = {'version': 1, 'disable_existing_loggers': False,
           'handlers': {'console': {'class': 'logging.StreamHandler'}},
           'loggers': {'supply.audit': {'handlers': ['console'], 'level': 'INFO', 'propagate': False}}}
