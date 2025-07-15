# File: django-rpa-relay-standalone/relay_server/urls.py
from django.urls import path
from . import views

app_name = 'relay'

urlpatterns = [
    # Command control
    path('node/filter/', views.NodeMetadataView.as_view(), name='nodes_metadata'),
    path('<str:batch_id>/node/<str:node_id>/request/<str:request_id>/', views.RequestView.as_view(), name='command_send'),
    path('<str:batch_id>/node/<str:node_id>/response/<str:request_id>/', views.ResponseView.as_view(), name='command_status'),
    path('<str:batch_id>/node/<str:node_id>/release/', views.NodeReleaseView.as_view()),

    # File retrieval by batch server
    # path('files/fetch/', views.FileFetchView.as_view(), name='file_fetch'),

    # # Metadata endpoints
    # path('orchestrators/metadata/', views.OrchestratorMetadataView.as_view(), name='orchestrators_metadata'),
]
