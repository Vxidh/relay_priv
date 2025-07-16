from django.urls import re_path
from .consumers import NodeImageConsumer, ControllerCommandConsumer

websocket_urlpatterns = [
    re_path(r"ws/remote-control/image/(?P<node_id>[A-Za-z0-9_-]+)/", NodeImageConsumer.as_asgi()),
    re_path(r"ws/remote-control/command/(?P<node_id>[A-Za-z0-9_-]+)/", ControllerCommandConsumer.as_asgi()),
]
