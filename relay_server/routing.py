from django.urls import re_path
from .consumers import NodeConsumer

# This is the list of WebSocket URL patterns that asgi.py will import.
websocket_urlpatterns = [
    re_path(r"ws/rpa-node/(?P<node_id>[A-Za-z0-9]{6})/", NodeConsumer.as_asgi()),
]
