# File: django-rpa-relay-standalone/rpa_relay_server_project/settings.py
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


SECRET_KEY = 'django-insecure-m+a668t=3e=7c*b6k0y%3d6k^r4r6z(e(e9h4^@l6!a5+m^o_o' # Change this in production!
DEBUG = True # Set to False in production
ALLOWED_HOSTS = ['localhost', '127.0.0.1']

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'channels',
    'relay_server',
    'remote_control_app',
    'oauth2_provider',
    'rest_framework',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'rpa_relay_server_project.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'rpa_relay_server_project.wsgi.application'
ASGI_APPLICATION = 'rpa_relay_server_project.asgi.application' 

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3', 
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
OAUTH2_PROVIDER_APPLICATION_MODEL = 'oauth2_provider.Application'
LOGIN_URL = '/admin/login/'
BATCH_SERVER_FILE_UPLOAD_URL = "http://your-batch-server:8001/api/file-receive/"
BATCH_SERVER_API_KEY = "your_super_secret_batch_server_key"
BATCH_SERVER_URL = "http://localhost:8080"



AUTHENTICATION_BACKENDS = (
    'oauth2_provider.backends.OAuth2Backend', # For authenticating with OAuth2 tokens
    'django.contrib.auth.backends.ModelBackend', # Django's default for username/password
)

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'oauth2_provider.contrib.rest_framework.OAuth2Authentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated', # Require authentication by default
    ),
}

OAUTH2_PROVIDER = {
    # These are default scopes. You can define custom scopes as needed.
    # The 'read' and 'write' are common. For RPA nodes, you might need more specific scopes.
    'SCOPES': {
        'read': 'Read scope',
        'write': 'Write scope',
        'rpa:connect': 'Allows an RPA node to establish a WebSocket connection',
        'rpa:commands': 'Allows an RPA node to receive commands',
        'rpa:register': 'Allows a new RPA node to register and get tokens',
        # Add more granular scopes as your application grows
    },
    'ACCESS_TOKEN_EXPIRE_SECONDS': 3600 * 24 * 30, # Example: 30 days expiry for access tokens
    'REFRESH_TOKEN_EXPIRE_SECONDS': 3600 * 24 * 365, # Example: 1 year expiry for refresh tokens
    # Using 'authorization-code' means the default grant types are available.
    # For a client credential or custom flow, you might adjust this.
    'DEFAULT_SCOPES': ['rpa:connect', 'rpa:commands'], # Default scopes to grant if none are requested
    'OAUTH2_VALIDATOR_CLASS': 'relay_server.oauth2_validators.CustomOAuth2Validator',
    'PKCE_REQUIRED': True, # Enforce PKCE for public clients (recommended for security)
}

CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels.layers.InMemoryChannelLayer',
    },
}

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'standard': {
            'format': '[{levelname}] {asctime} {name}:{funcName}():{lineno} - {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'level': 'INFO',
            'class': 'logging.StreamHandler',
            'formatter': 'standard',
        },
        'file': {
            'level': 'DEBUG',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': BASE_DIR / 'logs' / 'relay_server.log',
            'maxBytes': 1024 * 1024 * 5,
            'backupCount': 3,
            'formatter': 'standard',
        },
    },
    'root': {
        'handlers': ['console', 'file'],
        'level': 'INFO',    
    },
    'loggers': {
        'relay_server': {
            'handlers': ['console', 'file'],
            'level': 'DEBUG',
            'propagate': False,
        },
    },
}