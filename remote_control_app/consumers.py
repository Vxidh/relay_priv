# File: remote_control_app/consumers.py (MODIFIED - Simplified RC Input Forwarding)

import json
import logging
import asyncio
from datetime import datetime
from channels.generic.websocket import AsyncWebsocketConsumer
from django.utils import timezone
from oauth2_provider.models import AccessToken
from channels.db import database_sync_to_async

# Import NodeConsumer and nodes_available from relay_server for cross-consumer communication
try:
    from relay_server.consumers import nodes_available
except ImportError:
    logging.error("Could not import nodes_available from relay_server.consumers. "
                  "Ensure relay_server.consumers is properly structured or provide an alternative.")
    nodes_available = {}

logger = logging.getLogger(__name__)

# --- In-memory state for Remote Control connections ---
connected_rc_agents = {}
connected_rc_viewers = {}

class CustomJsonEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        return json.JSONEncoder.default(self, obj)

@database_sync_to_async
def get_token_and_user(token_str):
    # ... (unchanged authentication logic) ...
    if not token_str:
        return None

    try:
        token_obj = AccessToken.objects.select_related("user").get(token=token_str)
        if token_obj.is_expired():
            logger.warning(f"Authentication failed: Token {token_str[:8]}... expired.")
            return None
        if not token_obj.user.is_active:
            logger.warning(f"Authentication failed: User {token_obj.user.username} is inactive.")
            return None
        return token_obj.user
    except AccessToken.DoesNotExist:
        logger.warning(f"Authentication failed: Invalid token {token_str[:8]}... provided.")
        return None
    except Exception as e:
        logger.exception(f"Error during token validation for {token_str[:8]}...: {e}")
        return None


class RemoteControlConsumer(AsyncWebsocketConsumer):
    json_encoder_class = CustomJsonEncoder

    async def connect(self):
        self.scope_type = self.scope['url_route']['kwargs']['scope_type']
        self.node_id = self.scope['url_route']['kwargs']['node_id']

        query_string = self.scope.get('query_string', b'').decode()
        query_params = dict(qc.split('=') for qc in query_string.split('&') if '=' in qc)
        token = query_params.get('token')

        user = await get_token_and_user(token)
        if not user:
            logger.warning(f"RC WS connection rejected: Invalid or missing token from {self.scope_type} {self.node_id}.")
            await self.close(code=4003)
            return

        self.scope['user'] = user
        logger.info(f"RC WS connection from user '{user.username}' for {self.scope_type} '{self.node_id}' accepted.")

        if self.scope_type == 'agent':
            if self.node_id in connected_rc_agents:
                logger.warning(f"Duplicate RC Agent connection for node_id {self.node_id}. Rejecting.")
                await self.close(code=4009)
                return
            connected_rc_agents[self.node_id] = self
            logger.info(f"RC Agent {self.node_id} registered. Total agents: {len(connected_rc_agents)}")

            if self.node_id in connected_rc_viewers and connected_rc_viewers[self.node_id]:
                logger.info(f"RC Agent {self.node_id} connected. Sending 'start_control' as viewers are present.")
                await self.send_start_control()

        elif self.scope_type == 'viewer':
            connected_rc_viewers.setdefault(self.node_id, set()).add(self)
            logger.info(f"RC Viewer for node {self.node_id} registered. Total viewers for {self.node_id}: {len(connected_rc_viewers[self.node_id])}")

            if len(connected_rc_viewers[self.node_id]) == 1 and self.node_id in connected_rc_agents:
                logger.info(f"First RC Viewer for node {self.node_id} connected. Signalling agent to 'start_control'.")
                await connected_rc_agents[self.node_id].send_start_control()
            elif self.node_id not in connected_rc_agents:
                logger.warning(f"RC Viewer for node {self.node_id} connected, but agent is not available.")
                await self.send(text_data=json.dumps({"type": "status", "message": "Remote control agent is offline."}))

        await self.accept()

    async def disconnect(self, close_code):
        if self.scope_type == 'agent':
            if self.node_id in connected_rc_agents:
                del connected_rc_agents[self.node_id]
                logger.info(f"RC Agent {self.node_id} disconnected with code {close_code}. Total agents: {len(connected_rc_agents)}")
                if self.node_id in connected_rc_viewers:
                    for viewer in list(connected_rc_viewers[self.node_id]):
                        try:
                            await viewer.send(text_data=json.dumps({"type": "status", "message": "Remote control agent disconnected."}))
                        except Exception as e:
                            logger.error(f"Error sending agent disconnect status to viewer: {e}")

        elif self.scope_type == 'viewer':
            if self.node_id in connected_rc_viewers:
                connected_rc_viewers[self.node_id].discard(self)
                logger.info(f"RC Viewer for node {self.node_id} disconnected with code {close_code}. Remaining viewers: {len(connected_rc_viewers[self.node_id])}")
                if not connected_rc_viewers[self.node_id]:
                    if self.node_id in connected_rc_agents:
                        logger.info(f"Last RC Viewer for node {self.node_id} disconnected. Signalling agent to 'stop_control'.")
                        await connected_rc_agents[self.node_id].send_stop_control()
                    del connected_rc_viewers[self.node_id]

        logger.info(f"RC WS connection for {self.scope_type} '{self.node_id}' closed with code {close_code}.")

    async def receive(self, text_data):
        try:
            message = json.loads(text_data)
            msg_type = message.get('type')

            logger.debug(f"RC Consumer received message type '{msg_type}' from {self.scope_type} {self.node_id}.")

            if self.scope_type == 'agent':
                if msg_type == 'remote_control_frame':
                    image_base64 = message.get('image_base64')
                    timestamp = message.get('timestamp', timezone.now().isoformat())

                    if image_base64:
                        viewers = connected_rc_viewers.get(self.node_id)
                        if viewers:
                            frame_payload = json.dumps({
                                "type": "remote_control_frame",
                                "image_base64": image_base64,
                                "timestamp": timestamp,
                                "node_id": self.node_id,
                            }, cls=self.json_encoder_class)

                            for viewer in list(viewers):
                                try:
                                    await viewer.send(text_data=frame_payload)
                                except Exception as e:
                                    logger.error(f"Error sending frame to viewer {viewer} for node {self.node_id}: {e}")
                                    viewers.discard(viewer)
                        else:
                            logger.debug(f"No viewers connected for node {self.node_id} to receive remote_control_frame.")
                    else:
                        logger.warning(f"remote_control_frame from agent {self.node_id} missing image_base64.")
                else:
                    logger.warning(f"RC Agent {self.node_id} sent unhandled message type: {msg_type}.")

            elif self.scope_type == 'viewer':
                # Messages from the RC Viewer (Web browser) - these are input commands
                # We expect these to be a subset of your standard RPA commands
                # e.g., {"type": "mouse_click", "params": {"x": 100, "y": 200}}
                # Package this into the standard 'command' structure for the NodeClient
                
                # Check if it's an expected remote control input command type
                # You might want to define a whitelist of accepted input types from the viewer
                if msg_type in ['mouse_move', 'mouse_click', 'mouse_drag', 'mouse_scroll',
                                'key_press', 'key_combo', 'type_text', 'combo_click']:

                    node_consumer_instance = nodes_available.get(self.node_id)
                    if node_consumer_instance:
                        # Construct the standard 'command' payload
                        command_payload = {
                            "type": "command", # This is the crucial change: send as a regular 'command'
                            "command": {
                                "commandType": msg_type, # The original message type becomes commandType
                                "params": message.get('params', {}), # Pass original params
                                "requestId": f"rc_input_{self.node_id}_{timezone.now().timestamp()}" # Generate a unique ID
                            }
                        }
                        
                        try:
                            # Send this standard command directly to the NodeConsumer instance's WebSocket
                            # This will be received by NodeClient.on_message and processed by CommandDispatcher
                            await node_consumer_instance.send(text_data=json.dumps(command_payload, cls=self.json_encoder_class))
                            logger.info(f"Forwarded RC input command '{msg_type}' from viewer for node {self.node_id} to RPA Node.")
                        except Exception as e:
                            logger.exception(f"Error forwarding RC input command to RPA Node {self.node_id}: {e}")
                            await self.send(text_data=json.dumps({"type": "status", "message": f"Error forwarding command: {e}"}))
                    else:
                        logger.warning(f"NodeConsumer for node {self.node_id} not available to receive RC input command. Agent might be offline.")
                        await self.send(text_data=json.dumps({"type": "status", "message": "Remote control agent for input is offline."}))
                elif msg_type == 'status_check':
                    logger.debug(f"RC Viewer {self.node_id} sent status_check. Responding.")
                    await self.send(text_data=json.dumps({"type": "status_response", "message": "RC Viewer online."}))
                else:
                    logger.warning(f"RC Viewer {self.node_id} sent unhandled message type: {msg_type}.")

        except json.JSONDecodeError:
            logger.error(f"RC Consumer: Failed to decode JSON from WS message: {text_data[:500]}", exc_info=True)
        except Exception as e:
            logger.exception(f"RC Consumer: Unhandled error in receive() from {self.scope_type} {self.node_id}: {e}")

    async def send_start_control(self):
        message = {
            "type": "control_command",
            "command": {
                "commandType": "start_control",
                "timestamp": timezone.now().isoformat()
            }
        }
        try:
            await self.send(text_data=json.dumps(message, cls=self.json_encoder_class))
            logger.info(f"Sent 'start_control' command to RC Agent {self.node_id}.")
        except Exception as e:
            logger.error(f"Failed to send 'start_control' to RC Agent {self.node_id}: {e}")

    async def send_stop_control(self):
        message = {
            "type": "control_command",
            "command": {
                "commandType": "stop_control",
                "timestamp": timezone.now().isoformat()
            }
        }
        try:
            await self.send(text_data=json.dumps(message, cls=self.json_encoder_class))
            logger.info(f"Sent 'stop_control' command to RC Agent {self.node_id}.")
        except Exception as e:
            logger.error(f"Failed to send 'stop_control' to RC Agent {self.node_id}: {e}")