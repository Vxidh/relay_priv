# File: django-rpa-relay-standalone/rpa_relay_server_project/asgi.py
import os
import django
from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from django.core.asgi import get_asgi_application
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'rpa_relay_server_project.settings')
django.setup()


# Import websocket_urlpatterns from both relay_server and remote_control_app
from relay_server.routing import websocket_urlpatterns as relay_ws_urlpatterns
from remote_control_app.routing import websocket_urlpatterns as remote_ws_urlpatterns
from relay_server.auth_middleware import TokenAuthMiddleware

all_websocket_urlpatterns = relay_ws_urlpatterns + remote_ws_urlpatterns

application = ProtocolTypeRouter({
    "http": get_asgi_application(),
    "websocket": TokenAuthMiddleware(
        AuthMiddlewareStack(
            URLRouter(all_websocket_urlpatterns)
        )
    ),
})
