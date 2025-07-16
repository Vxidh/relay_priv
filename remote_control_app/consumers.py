# remote_control_app/consumers.py

from channels.generic.websocket import AsyncWebsocketConsumer
import json
import logging

from relay_server.consumers import nodes_available, node_connections

logger = logging.getLogger(__name__)

# UI <-> Image stream connections
node_image_connections = {}
controller_command_connections = {}

class NodeImageConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.node_id = self.scope['url_route']['kwargs']['node_id']
        
        # Determine if this is a node or frontend connection
        # You can check headers, query params, or user agent
        headers = dict(self.scope.get('headers', []))
        authorization = headers.get(b'authorization', b'').decode()
        
        # If it has Bearer token, it's likely the node
        if authorization.startswith('Bearer '):
            self.connection_type = 'node'
            connection_key = f"{self.node_id}_node"
        else:
            self.connection_type = 'frontend'
            connection_key = f"{self.node_id}_frontend"
        
        node_image_connections[connection_key] = self
        logger.info(f"[NodeImage] {self.connection_type.title()} for node {self.node_id} connected and accepted.")
        await self.accept()

    async def disconnect(self, close_code):
        # Remove based on connection type
        if self.connection_type == 'node':
            connection_key = f"{self.node_id}_node"
        else:
            connection_key = f"{self.node_id}_frontend"
            
        if connection_key in node_image_connections:
            del node_image_connections[connection_key]
            logger.info(f"[NodeImage] {self.connection_type.title()} for node {self.node_id} disconnected.")

        # Rest of your disconnect logic...

    async def receive(self, text_data=None, bytes_data=None):
        if bytes_data:
            logger.info(f"[NodeImage] Received {len(bytes_data)} bytes from {self.connection_type} {self.node_id}")
            
            # Only nodes should send binary data to frontend
            if self.connection_type == 'node':
                frontend_connection = node_image_connections.get(f"{self.node_id}_frontend")
                
                if frontend_connection:
                    await frontend_connection.send(bytes_data=bytes_data)
                    logger.info(f"[NodeImage] Forwarded {len(bytes_data)} bytes to frontend")
                else:
                    logger.warning(f"[NodeImage] No frontend image connection for node {self.node_id}")
                    await self.send(text_data=json.dumps({
                        'type': 'error',
                        'message': 'No frontend connected to image stream.'
                    }))
            else:
                logger.warning(f"[NodeImage] Frontend sent binary data unexpectedly")
                
        elif text_data:
            logger.warning(f"[NodeImage] Unexpected text from {self.connection_type} {self.node_id}: {text_data}")

class ControllerCommandConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.node_id = self.scope['url_route']['kwargs']['node_id']

        if self.node_id in controller_command_connections:
            await self.close(code=4003)
            return

        await self.accept()
        controller_command_connections[self.node_id] = self
        logger.info(f"[Controller] Controller connected for node {self.node_id}.")

        await self.send(text_data=json.dumps({
            "type": "ready",
            "message": f"Connected to relay for node {self.node_id}"
        }))
        logger.info(f"[Controller] Sent 'ready' to controller for node {self.node_id}.")

    async def disconnect(self, close_code):
        if self.node_id in controller_command_connections:
            del controller_command_connections[self.node_id]
            logger.info(f"[Controller] Controller for node {self.node_id} disconnected.")

        node = node_image_connections.get(self.node_id)
        if node:
            try:
                await node.send(text_data=json.dumps({
                    'type': 'error',
                    'message': 'Controller disconnected.'
                }))
                await node.close(code=4004)
            except Exception:
                logger.warning(f"[Controller] Failed to notify node of controller disconnection.")

    async def receive(self, text_data=None, bytes_data=None):
        logger.info(f"[Controller] Received command for node {self.node_id}: {text_data}")
        node = nodes_available.get(self.node_id)

        if node and text_data:
            try:
                cmd = json.loads(text_data)
                request_id = cmd.get("requestId", "unknown")
                await node.send_command_to_node(request_id, cmd)
                logger.info(f"[Controller] Bridged command '{cmd.get('commandType')}' to node {self.node_id}")
            except Exception as e:
                logger.exception(f"[Controller] Failed to forward command to node {self.node_id}.")
                await self.send(text_data=json.dumps({
                    'type': 'error',
                    'message': f'Failed to send command: {str(e)}'
                }))
        else:
            logger.warning(f"[Controller] No active node found for {self.node_id}.")
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'No node connected to relay.'
            }))
