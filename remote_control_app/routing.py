from django.urls import re_path
from .consumers import RemoteControlConsumer

websocket_urlpatterns = [
    # WebSocket for Remote Control Agents (Python Clients to push screen frames)
    # Example: ws://localhost:8000/ws/rc-agent/ABC123/?token=<access_token>
    re_path(
        r"ws/rc-agent/(?P<node_id>[A-Za-z0-9]{6})/",
        RemoteControlConsumer.as_asgi(),
        {'scope_type': 'agent'} # Pass scope_type as a kwarg to the consumer
    ),
    # WebSocket for Remote Control Viewers (Web Browsers to receive frames and send input)
    # Example: ws://localhost:8000/ws/rc-viewer/ABC123/?token=<access_token>
    re_path(
        r"ws/rc-viewer/(?P<node_id>[A-Za-z0-9]{6})/",
        RemoteControlConsumer.as_asgi(),
        {'scope_type': 'viewer'} # Pass scope_type as a kwarg to the consumer
    ),
]