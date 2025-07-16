# File: NodeClient.py

import websocket
import json
import threading
import uuid
import os
import queue
import logging
import traceback
import base64
import time

from commands import CommandDispatcher # Assuming commands.py is where CommandDispatcher is defined

logger = logging.getLogger('NodeClient')

class NodeClient:

    def connect_image_stream(self):
        try:
            image_url = f"{self.server_url_base}/ws/remote-control/image/{self.node_id}/"
            headers = [f"Authorization: Bearer {self.access_token}"] if self.access_token else []
            
            self.image_ws = websocket.create_connection(image_url, header=headers)
            logger.info(f"NodeClient: Connected to image stream WebSocket at {image_url}.")
        except Exception as e:
            logger.exception(f"NodeClient: Failed to connect to image stream WebSocket: {e}")
            self.image_ws = None


    def send_image_frame(self, img_bytes):
        try:
            if self.image_ws:
                self.image_ws.send(img_bytes, opcode=websocket.ABNF.OPCODE_BINARY)
                logger.info(f"NodeClient: Sent image frame ({len(img_bytes)} bytes) to image stream.")
            else:
                logger.warning("NodeClient: Image WebSocket not connected. Cannot send image frame.")
        except Exception as e:
            logger.exception(f"NodeClient: Error sending image frame: {e}")

    def __init__(self, server_url, node_id, access_token, download_dir, initial_metadata=None, on_node_id_invalid=None):
        self.server_url = server_url
        self.node_id = node_id
        self.access_token = access_token
        self.download_dir = download_dir
        self.initial_metadata = initial_metadata if initial_metadata is not None else {}

        self.ws = None
        self.running = False
        self.current_task_state = {}
        self.image_ws = None  # Dedicated WebSocket for image streaming
        # Ensure CommandDispatcher is initialized with a reference to this NodeClient
        self.dispatcher = CommandDispatcher(node_client_ref=self)

        self.command_queue = queue.Queue()
        self.outgoing_ws_queue = queue.Queue()

        self.worker_thread = threading.Thread(target=self._command_worker, daemon=True)
        self._ws_sender_thread = threading.Thread(target=self._websocket_sender, daemon=True)

        self._connected_event = threading.Event()

        # Callback for handling invalid node ID (close code 4409)
        self.on_node_id_invalid = on_node_id_invalid

    def is_connected(self):
        # Check if the event is set AND if the websocket connection is active
        return self._connected_event.is_set() and self.ws and self.ws.sock and self.ws.sock.connected

    def on_message(self, ws, message):
        try:
            data = json.loads(message)
            msg_type = data.get('type')

            if msg_type == 'command':
                command_data = data.get('command')
                # The requestId is now expected directly in the command_data payload
                request_id = command_data.get('requestId')
                if command_data:
                    logger.info(f"NodeClient: Received command (Req ID: {request_id}). Queuing for worker.")
                    # Put the entire command_data dictionary into the queue
                    self.command_queue.put(command_data)
                else:
                    logger.warning(f"NodeClient: Received 'command' type message without 'command' data: {message}")
            elif msg_type == 'node_status_check':
                logger.info("NodeClient: Received node_status_check from server. Sending pong.")
                # For status checks, we don't have an original requestId, so use a placeholder or generate new
                # If the orchestrator doesn't poll for this, "N/A" is fine.
                self._send_command_response("N/A", "PONG", {"message": "Client is alive."})
            elif msg_type == 'send_file_to_node':
                # This block handles files sent *from* the Relay Server *to* the node.
                # This is separate from the node *uploading* files to the server.
                file_info = data.get('file', {})
                request_id = file_info.get('requestId') or file_info.get('request_id')
                filename = file_info.get('filename')
                file_content_b64 = file_info.get('file_content')

                if not (request_id and filename and file_content_b64):
                    logger.error(f"NodeClient: Malformed 'send_file_to_node' message: {file_info}")
                    # Use _send_command_response to send error back to relay
                    self._send_command_response(request_id, "error", error_message="Malformed file transfer message from server.")
                    return

                try:
                    decoded_content = base64.b64decode(file_content_b64)
                    save_path = os.path.join(self.download_dir, filename)
                    os.makedirs(os.path.dirname(save_path), exist_ok=True)
                    with open(save_path, "wb") as f:
                        f.write(decoded_content)
                    logger.info(f"NodeClient: Successfully received and saved file '{filename}' to '{save_path}'.")
                    # Send success response back to relay
                    self._send_command_response(request_id, "success", response_payload={
                        "message": f"File '{filename}' received and saved.",
                        "local_path": save_path,
                        "file_size": len(decoded_content)
                    })
                except Exception as e:
                    logger.exception(f"NodeClient: Error processing file transfer from server for requestId {request_id}: {e}")
                    self._send_command_response(request_id, "error", error_message=f"Error saving file from server: {str(e)}")

            else:
                logger.warning(f"NodeClient: Received unknown message type: {msg_type}")
        except json.JSONDecodeError:
            logger.error(f"NodeClient: Failed to decode JSON from WS message: {message}")
        except Exception as e:
            logger.exception(f"NodeClient: Error in on_message handler: {e}")

    def on_error(self, ws, error):
        logger.error(f"NodeClient: WebSocket Error: {error}")
        self._connected_event.clear()
        self.running = False # Set running to False on error to stop threads

    def on_close(self, ws, close_status_code, close_msg):
        logger.warning(f"NodeClient: WebSocket Closed. Status Code: {close_status_code}, Message: {close_msg}")
        self._connected_event.clear()
        self.running = False # Set running to False on close to stop threads

        if close_status_code == 4409:
            logger.error("NodeClient: Node ID invalid or already active (4409). Triggering node ID invalid callback.")
            if self.on_node_id_invalid:
                self.on_node_id_invalid()

    def on_open(self, ws):
        logger.info("NodeClient: WebSocket connection opened successfully.")
        self._connected_event.set()
        self.running = True # Ensure running is True when connection opens
        self._start_threads() # Start worker threads after connection is open
        # Connect to the image stream socket
        self.connect_image_stream()

        initial_request_id = str(uuid.uuid4())
        # Send initial node metadata message
        # The 'type' is now 'node_metadata' and node_id is at the top level
        self.send_outgoing_ws_message({
            "type": "node_response",
            "response": {
                "requestId": initial_request_id, # Use the generated request ID
                "status": "node_connected", # A status indicating initial connection
                "message": "Node client connected and sent initial metadata.",
                "responsePayload": { # Nest node_id and metadata here
                    "node_id": self.node_id,
                    "metadata": self.initial_metadata
                },
                "timestamp": time.time(),
                "node_id": self.node_id # Redundant but harmless, for clarity on server side
            }
        })
        logger.info(f"NodeClient: Sent initial node metadata (Req ID: {initial_request_id}): {self.initial_metadata}")

    # --- MODIFIED: _command_worker to correctly extract and pass requestId and send response ---
    def _command_worker(self):
        logger.info("NodeClient: Command worker thread started.")
        while self.running:
            command_data = None  # Initialize to None for the scope of the loop
            try:
                # Get the full command dictionary, which includes 'requestId' from the Orchestrator
                command_data = self.command_queue.get(timeout=1)

                command_type = command_data.get('commandType', 'N/A')
                # Extract the Orchestrator-generated requestId
                request_id = command_data.get('requestId')

                logger.info(f"NodeClient: Worker processing command: {command_type} (Req ID: {request_id})")

                # Execute the command via the dispatcher and capture its result
                # The dispatcher's execute_command method now returns a dictionary
                result_from_dispatcher = self.dispatcher.execute_command(command_data)

                # Send this result back to the Relay Server via _send_command_response
                # The result_from_dispatcher should already contain 'status', 'message', 'response', 'requestId'
                # We need to map these to the parameters of _send_command_response
                self._send_command_response(
                    request_id=result_from_dispatcher.get('requestId', request_id), # Use requestId from result or original
                    status=result_from_dispatcher.get('status', 'ERROR'),
                    response_payload=result_from_dispatcher.get('response', {}), # Pass the inner 'response' as payload
                    error_message=result_from_dispatcher.get('message') if result_from_dispatcher.get('status') == 'error' else None,
                    traceback=result_from_dispatcher.get('traceback')
                )

            except queue.Empty:
                # No command in queue, just continue loop. Do NOT call task_done() here.
                continue
            except Exception as e:
                # This block handles errors *during the processing* of command_data
                logger.exception(f"NodeClient: Critical error in command worker loop for Req ID {request_id if 'request_id' in locals() else 'UNKNOWN'}: {e}")
                # Attempt to send an error response if a requestId is available
                current_request_id = command_data.get('requestId') if command_data is not None else 'UNKNOWN'
                self._send_command_response(
                    current_request_id,
                    "ERROR", # Changed to ERROR for critical worker errors
                    error_message=f"Internal client processing error: {str(e)}",
                    traceback=traceback.format_exc()
                )
            finally:
                # Ensure task_done is called ONLY if an item was successfully retrieved from the queue
                if command_data is not None:
                    self.command_queue.task_done()
        logger.info("NodeClient: Command worker thread stopped.")

    def _websocket_sender(self):
        logger.info("NodeClient: WebSocket sender thread started.")
        while self.running:
            try:
                message_to_send = self.outgoing_ws_queue.get(timeout=1)
                if self.ws and self.ws.sock and self.ws.sock.connected:
                    self.ws.send(json.dumps(message_to_send)) # Ensure message is dumped to JSON string
                    logger.debug(f"NodeClient: Sent WS message type: {message_to_send.get('type')}, Req ID: {message_to_send.get('response', {}).get('requestId')}")
                else:
                    logger.warning("NodeClient: WebSocket not connected, re-queuing message for later.")
                    self.outgoing_ws_queue.put(message_to_send)
                    time.sleep(1) # Wait before retrying
                self.outgoing_ws_queue.task_done()
            except queue.Empty:
                time.sleep(0.1) # Small sleep to prevent busy-waiting
                continue
            except Exception as e:
                logger.exception(f"NodeClient: Error in WebSocket sender: {e}")
                self.running = False # Stop sender thread on critical error
        logger.info("NodeClient: WebSocket sender thread stopped.")

    def send_outgoing_ws_message(self, message):
        self.outgoing_ws_queue.put(message)

    # --- MODIFIED: _send_command_response to accept and use request_id ---
    def _send_command_response(self, request_id, status, response_payload=None, error_message=None, traceback=None):
        """
        Sends a standard command response to the Relay Server via WebSocket.
        Uses the request_id provided by the Orchestrator.
        """
        response_message = {
            "type": "node_response",
            "response": {
                "requestId": request_id, # Use the received request_id here
                "status": status,
                "responsePayload": response_payload if response_payload is not None else {},
                "error": error_message,
                "traceback": traceback,
                "node_id": self.node_id, # Include node_id in response for clarity
                "timestamp": time.time()
            }
        }
        self.send_outgoing_ws_message(response_message)
        logger.info(f"NodeClient: Queued response for requestId '{request_id}' with status '{status}'.")

    # --- MODIFIED: send_file_to_relay to accept and use request_id from Orchestrator ---
    def send_file_to_relay(self, file_path, request_id, metadata=None): # Renamed original_request_id to request_id for consistency
        """
        Sends a file from the RPA client to the Django Relay Server via WebSocket.
        This method is called by the CommandDispatcher when a command instructs
        the client to upload a file as a response.
        """
        if not os.path.exists(file_path):
            logger.error(f"NodeClient: File not found for upload: {file_path}")
            # Use _send_command_response for error reporting
            self._send_command_response(request_id, "error", error_message=f"File not found: {file_path}")
            return False
        
        if not os.path.isfile(file_path):
            logger.error(f"NodeClient: Path is not a file: {file_path}")
            self._send_command_response(request_id, "error", error_message=f"Path is not a file: {file_path}")
            return False

        try:
            with open(file_path, "rb") as f:
                file_content = f.read()
            encoded_content = base64.b64encode(file_content).decode('utf-8')
            file_name = os.path.basename(file_path)
            file_size = os.path.getsize(file_path)

            # Construct the file_details payload
            file_details_payload = {
                "request_id": request_id, # Use the received request_id here
                "node_id": self.node_id,
                "filename": file_name,
                "file_size": file_size,
                "file_content_base64": encoded_content,
                "timestamp": time.time(),
                "metadata": metadata if metadata is not None else {"description": f"File uploaded from RPA node {self.node_id}"}
            }

            # Wrap it in the 'response' structure as expected by consumers.py
            response_message = {
                "type": "node_response", # Type must be 'node_response' for consumers.py
                "response": {
                    "requestId": request_id, # This is the requestId at the response level
                    "status": "file_upload_complete", # Indicate file upload success
                    "message": f"File '{file_name}' uploaded.",
                    "node_id": self.node_id, # Redundant but harmless, for clarity
                    "file_details": file_details_payload # Nested file details
                }
            }
            
            self.send_outgoing_ws_message(response_message)
            logger.info(f"NodeClient: Queued file '{file_name}' for upload to Relay Server via WebSocket for Req ID: {request_id}.")
            return True
        except Exception as e:
            logger.exception(f"NodeClient: An unexpected error occurred during file upload preparation: {e}")
            self._send_command_response(request_id, "error", error_message=f"Error preparing file for upload: {str(e)}")
            return False

    def _start_threads(self):
        # Ensure threads are only started if not already running
        if self.worker_thread is None or not self.worker_thread.is_alive():
            self.worker_thread = threading.Thread(target=self._command_worker, daemon=True)
            self.worker_thread.start()
            logger.debug("NodeClient: Command worker thread started.")
        else:
            logger.debug("NodeClient: Command worker thread is already running.")

        if self._ws_sender_thread is None or not self._ws_sender_thread.is_alive():
            self._ws_sender_thread = threading.Thread(target=self._websocket_sender, daemon=True)
            self._ws_sender_thread.start()
            logger.debug("NodeClient: WebSocket sender thread started.")
        else:
            logger.debug("NodeClient: WebSocket sender thread is already running.")

    def connect(self):
        logger.info(f"NodeClient: Attempting to connect to: {self.server_url}")

        headers = [f"Authorization: Bearer {self.access_token}"] if self.access_token else []
        if headers:
            logger.info("NodeClient: Including Authorization header for WebSocket connection.")
        else:
            logger.warning("NodeClient: No access token provided for WebSocket connection. Connection might fail due to lack of authentication.")

        websocket.enableTrace(False)
        self.server_url_base = self.server_url.split("/ws/")[0]
        self.ws = websocket.WebSocketApp(
            self.server_url,
            header=headers,
            on_open=self.on_open,
            on_message=self.on_message,
            on_error=self.on_error,
            on_close=self.on_close
        )

        logger.info("NodeClient: WebSocketApp created. Calling run_forever...")
        # run_forever will block, so it needs to be in a separate thread if main thread needs to do other things
        # However, NodeClient.connect is typically called in a separate thread from main.py
        self.ws.run_forever(ping_interval=10, ping_timeout=5, reconnect=5)
        logger.info("NodeClient: WebSocket run_forever stopped.")
