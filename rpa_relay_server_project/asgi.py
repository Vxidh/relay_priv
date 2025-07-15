import os
import django
from channels.routing import ProtocolTypeRouter, URLRouter
from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'rpa_relay_server_project.settings')
django.setup()
from relay_server.routing import websocket_urlpatterns as relay_server_websocket_urlpatterns
from remote_control_app.routing import websocket_urlpatterns as remote_control_websocket_urlpatterns

# Import your custom TokenAuthMiddleware
from relay_server.auth_middleware import TokenAuthMiddleware

# Combine the WebSocket URL patterns from both apps
# This ensures that both sets of WebSocket endpoints are available
all_websocket_urlpatterns = (
    relay_server_websocket_urlpatterns +
    remote_control_websocket_urlpatterns
)

application = ProtocolTypeRouter({
    "http": get_asgi_application(),  # Handles standard HTTP requests
    "websocket": TokenAuthMiddleware( # Apply TokenAuthMiddleware to all WebSocket connections
        URLRouter(all_websocket_urlpatterns)
    ),
})