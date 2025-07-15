# File: django-rpa-relay-standalone/rpa_relay_server_project/asgi.py
import os
import django
from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from django.core.asgi import get_asgi_application
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'rpa_relay_server_project.settings')
django.setup()

# Now, import your root WebSocket URL routing after Django settings are configured
from relay_server.routing import websocket_urlpatterns
from relay_server.auth_middleware import TokenAuthMiddleware

application = ProtocolTypeRouter({
    "http": get_asgi_application(),  # Handles standard HTTP requests
    "websocket": TokenAuthMiddleware(
        URLRouter(websocket_urlpatterns)
    ),
})
