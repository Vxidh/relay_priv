# django-rpa-relay-standalone/rpa_relay_server_project/wsgi.py
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'rpa_relay_server_project.settings')

application = get_wsgi_application()