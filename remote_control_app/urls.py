# File: remote_control_app/urls.py

from django.urls import path
from . import views
app_name = 'remote_control_app'

urlpatterns = [
    # HTTP endpoint to serve the remote control viewer HTML page
    # Example: http://localhost:8000/remote-control/viewer/
    path('viewer/', views.remote_control_viewer_page, name='remote_control_viewer_page'),
]