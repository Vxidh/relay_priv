# File: django-rpa-relay-standalone/relay_server/views.py

import logging
import json
from django.http import JsonResponse, HttpResponse
from django.views import View 

# Import Django REST Framework components
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
# CHANGED: Import AllowAny for temporary debugging
from rest_framework.permissions import AllowAny, IsAuthenticated 

# Import OAuth2 authentication (assuming you're using django-oauth-toolkit)
from oauth2_provider.contrib.rest_framework import OAuth2Authentication

# Import async_to_sync for calling async consumer methods from sync views
from asgiref.sync import async_to_sync

from channels.db import database_sync_to_async

from .consumers import nodes_available, req_resp, node_connections

logger = logging.getLogger(__name__)

# --- APIView for handling RPA Command Requests (from Orchestrator to RPA Node) ---
class RequestView(APIView):
    authentication_classes = [OAuth2Authentication]
    def dispatch(self, request, *args, **kwargs):
        print(f"\n--- DEBUGGING: RequestView.dispatch called for URL: {request.path} ---")
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, batch_id, node_id, request_id, *args, **kwargs):
        command_payload = request.data

        logger.info(f"RequestView: Received command for node {node_id}, request {request_id}: {command_payload}")

        target_consumer = nodes_available.get(node_id)
        if not target_consumer:
            logger.warning(f"RequestView: Target node {node_id} is not connected via WebSocket. Req ID: {request_id} not sent.")
            return Response({
                "status": "node_unavailable",
                "message": f"RPA Node {node_id} is not currently connected.",
                "request_id": request_id
            }, status=status.HTTP_200_OK)

        try:
            async_to_sync(target_consumer.send_command_to_node)(request_id, command_payload) 

            return Response({"status": "command_sent", "request_id": request_id}, status=status.HTTP_202_ACCEPTED)
        except Exception as e:
            logger.exception(f"RequestView: Error sending command to node {node_id}, request {request_id}: {e}")
            return Response({"status": "error", "message": f"Failed to send command to node: {e}", "request_id": request_id}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# --- APIView for handling RPA Command Responses (from RPA Node to Orchestrator) ---
class ResponseView(APIView):
    authentication_classes = [OAuth2Authentication]

    def dispatch(self, request, *args, **kwargs):
        print(f"\n--- DEBUGGING: ResponseView.dispatch called for URL: {request.path} ---")
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, batch_id, node_id, request_id, *args, **kwargs):

        key = (node_id, request_id)
        
        interaction_list = req_resp.get(key)

        if not interaction_list or len(interaction_list) < 2:
            logger.info(f"ResponseView: No response found yet for node {node_id}, request {request_id} (batch {batch_id}).")
            return Response({"status": "pending", "message": "Response not yet received."}, status=status.HTTP_202_ACCEPTED)

        ret = interaction_list[1] 

        # --- LOGIC FOR FILE HANDLING ---
        if 'file_details' in ret:
            file_details = ret['file_details']
            filename = file_details.get('filename')
            file_content_base64 = file_details.get('file_content_base64')
            
            logger.info(f"ResponseView: Retrieving file '{filename}' for node {node_id}, request {request_id}.")

            response_data = {
                "status": "file_uploaded", 
                "request_id": request_id,
                "node_id": node_id,
                "filename": filename,
                "file_size": file_details.get('file_size'),
                "file_content_base64": file_content_base64, 
                "metadata": file_details.get('metadata', {}),
                "original_response_status": ret.get('status'), 
                "message": ret.get('message', f"File '{filename}' successfully uploaded and retrieved.")
            }
        else:
            logger.info(f"ResponseView: Retrieving regular command response for node {node_id}, request {request_id}.")
            response_data = {
                "status": ret.get('status', 'completed'), 
                "request_id": request_id,
                "node_id": node_id,
                "response": ret 
            }
        # --- END LOGIC ---

        del req_resp[key]
        logger.info(f"ResponseView: Deleted entry for node {node_id}, request {request_id} from req_resp.")
        
        return Response(response_data, status=status.HTTP_200_OK)

# --- Standard Django Views (no changes needed for CSRF if they don't accept POST from external clients) ---
class NodeMetadataView(View):
    def get(self, request, *args, **kwargs):
        query_params = request.GET
        filtered = {}
        for n_id, n in nodes_available.items():
            for qk, qv in query_params.items():
                if n.metadata and qk in n.metadata and str(n.metadata.get(qk)) == qv:
                    filtered[n_id] = n.metadata
        return JsonResponse(list(filtered.values()), safe=False)


class NodeReleaseView(View):
    def post(self, request, *args, **kwargs):
        node_id = kwargs.get('node_id')
        if node_id in node_connections:
            node_connections[node_id].close(code=1000) 
            del node_connections[node_id]
            logger.info(f"NodeReleaseView: Node {node_id} released and disconnected.")
            return JsonResponse({"status": "success", "message": f"Node {node_id} released."}, status=200)
        else:
            logger.warning(f"NodeReleaseView: Node {node_id} not found or already disconnected.")
            return JsonResponse({"status": "error", "message": f"Node {node_id} not found or already disconnected."}, status=404)

