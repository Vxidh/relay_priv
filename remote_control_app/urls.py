# remote_control_app/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('remote-control/', views.remote_control_entry, name='remote_control_entry'),
    path('remote-control/start/', views.start_remote_control, name='start_remote_control'),
    path('remote-control/stream/<str:node_id>/', views.stream_images, name='stream_images'),
]
