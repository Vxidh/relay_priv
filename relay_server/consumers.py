# File: relay_server/consumers.py

import json
import logging
import asyncio
import traceback
from channels.generic.websocket import AsyncWebsocketConsumer
from django.utils import timezone
from oauth2_provider.models import AccessToken
from django.utils.timezone import now
from datetime import datetime # <--- ADDED: Import datetime for custom JSON encoder
from django.contrib.auth import get_user_model
from channels.db import database_sync_to_async

User = get_user_model()
logger = logging.getLogger(__name__)

# Central state stores
req_resp = {}    # {(node_id, request_id): [request, response]}
nodes_available = {}
node_connections = {}

CLEANUP_INTERVAL_MINUTES = 60

class CustomJsonEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        return json.JSONEncoder.default(self, obj)

@database_sync_to_async
def get_token_and_user(token):
    token_obj = AccessToken.objects.select_related("user").get(token=token)
    if token_obj.is_expired():
        raise ValueError("Token expired")
    return token_obj

class NodeConsumer(AsyncWebsocketConsumer):
    cleanup_started = False  # Ensures cleanup task is only started once globally
    json_encoder_class = CustomJsonEncoder # <--- ADDED: Apply custom encoder to this consumer

    async def connect(self):
        self.node_id = self.scope['url_route']['kwargs']['node_id']

        # Extract and validate Bearer token
        headers = dict(self.scope['headers'])
        auth_header = headers.get(b'authorization')
        if not auth_header:
            logger.warning("Missing Authorization header in WebSocket connection.")
            await self.close(code=4001)
            return

        try:
            token_type, access_token = auth_header.decode().split()
            if token_type.lower() != 'bearer':
                raise ValueError("Authorization header is not Bearer")

            token_obj = await get_token_and_user(access_token)
            self.scope["user"] = token_obj.user
            logger.info(f"Authenticated WebSocket connection from user '{token_obj.user.username}'")

        except Exception as e:
            logger.exception("WebSocket token validation failed.")
            await self.close(code=4003)
            return

        # Avoid duplicate connections
        if self.node_id in nodes_available:
            logger.warning(f"Duplicate connection for node_id {self.node_id}. Rejecting.")
            await self.close()
            return

        # Register node
        nodes_available[self.node_id] = self
        node_connections[self.node_id] = ""

        self.metadata = {
            "node_id": self.node_id,
            "connected_to": None,
            "last_pinged": timezone.now(),
            "client_user": self.scope["user"].username,
        }

        # Start cleanup only once
        if not NodeConsumer.cleanup_started:
            asyncio.create_task(cleanup_commands())
            NodeConsumer.cleanup_started = True
            logger.info("Started cleanup_commands background task.")

        await self.accept()
        logger.info(f"RPA Node {self.node_id} connected and authenticated.")

    async def disconnect(self, close_code):
        nodes_available.pop(self.node_id, None)
        node_connections.pop(self.node_id, None)
        logger.info(f"WebSocket disconnected for node {self.node_id} with code {close_code}.")

    async def send_command_to_node(self, request_id, request_data):
        req_resp[(self.node_id, request_id)] = [request_data]

        command = {
            "type": "command",
            "command": request_data
        }
        await self.send(text_data=json.dumps(command)) 
        logger.info(f"Command sent to node {self.node_id} Req ID: {request_id}")

    async def receive(self, text_data=None, bytes_data=None):
        if text_data is None:
            return
        try:
            message = json.loads(text_data)
            msg_type = message.get('type')
            request_id = message.get('requestId') or message.get('response', {}).get('requestId')

            logger.info(f"Received message type '{msg_type}' from {self.node_id} (Req ID: {request_id})")

            if msg_type == 'node_response':
                response = message.get('response', {})
                req_id = response.get('requestId')
                if req_id:
                    req_resp.setdefault((self.node_id, req_id), []).append(response)
                    logger.info(f"Updated command status for {req_id}.")
                else:
                    logger.warning("Received node_response without valid requestId.")
            elif msg_type == 'file_upload':
                file_data = message.get('file', {})
                request_id = file_data.get('request_id')
                filename = file_data.get('filename')
                file_content_base64 = file_data.get('file_content') 
                uploaded_by_node_id = file_data.get('uploaded_by_node_id')
                mime_type = file_data.get('mime_type', 'application/octet-stream')
                file_size = file_data.get('file_size', 0)
                original_command_type = file_data.get('original_command_type', 'unknown')

                logger.info(f"Received file_upload from {uploaded_by_node_id} for Req ID: {request_id}, Filename: {filename}, Size: {file_size} bytes.")

                file_details_payload = {
                    "filename": filename,
                    "file_content_base64": file_content_base64, 
                    "file_size": file_size,
                    "mime_type": mime_type,
                    "original_command_type": original_command_type,
                    "request_id": request_id
                }
                
                response_payload = {
                    "status": "file_uploaded",
                    "request_id": request_id,
                    "message": f"File '{filename}' uploaded successfully.",
                    "file_details": file_details_payload,
                    "timestamp": now().isoformat() 
                }
                req_resp.setdefault((self.node_id, request_id), []).append(response_payload)
                logger.info(f"File upload status updated in req_resp for Req ID: {request_id}.")

            elif msg_type == 'image_frame':
                frame_data_base64 = message.get("frame_data")
                if not frame_data_base64:
                    logger.warning(f"Missing frame_data in image_frame from node {self.node_id}")
                    return

                if self.node_id in node_connections and node_connections[self.node_id]:
                    controller_channel = node_connections[self.node_id]
                    try:
                        import base64
                        binary_data = base64.b64decode(frame_data_base64)
                        await controller_channel.send(bytes_data=binary_data)
                        logger.info(f"Forwarded image_frame from node {self.node_id} to controller.")
                    except Exception as e:
                        logger.exception(f"Failed to forward image_frame from {self.node_id}: {e}")
                else:
                    logger.warning(f"No controller attached to node {self.node_id}; dropped image_frame.")


            else:
                logger.warning(f"Unknown message type: {msg_type}")

        except json.JSONDecodeError:
            logger.error(f"Invalid JSON from node {self.node_id}: {text_data}")
        except Exception as e:
            logger.exception(f"Error in receive() from {self.node_id}: {e}")


async def cleanup_commands():
    while True:
        await asyncio.sleep(CLEANUP_INTERVAL_MINUTES * 60)
        logger.info("Running cleanup on commands...")

        cutoff = timezone.now() - timezone.timedelta(minutes=CLEANUP_INTERVAL_MINUTES)
        keys_to_delete = []

        for key, data in req_resp.items():
            try:
                command_or_response = data[0] # Get the first item (usually the request)
                timestamp_str = command_or_response.get('time_stamp') or command_or_response.get('timestamp')

                if timestamp_str:
                    timestamp = datetime.fromisoformat(timestamp_str)
                    if timestamp < cutoff:
                        keys_to_delete.append(key)
                else:
                    logger.warning(f"Entry in req_resp for key {key} has no timestamp for cleanup.")

            except Exception as e:
                logger.warning(f"Malformed entry in req_resp for key {key} during cleanup: {e}")

        for key in keys_to_delete:
            req_resp.pop(key, None)
            logger.debug(f"Deleted stale data for requestId: {key}")

        logger.info(f"Cleanup complete. Deleted {len(keys_to_delete)} entries.")
