# File: python-client/NodeClient.py (REFACTORED FOR WEBSOCKETS/ASYNCIO)

import asyncio
import websockets
import json
import uuid
import os
import logging
import traceback
import base64
import time
from datetime import datetime, timezone
import threading # Import threading for managing the dedicated loop thread

from commands import CommandDispatcher

logger = logging.getLogger('NodeClient')

class NodeClient:
    def __init__(self, server_url, node_id, access_token, download_dir, initial_metadata=None, on_node_id_invalid=None):
        self.server_url = server_url
        self.node_id = node_id
        self.access_token = access_token
        self.download_dir = download_dir
        self.initial_metadata = initial_metadata if initial_metadata is not None else {}

        self._ws = None # Will hold the active websockets connection instance
        self._running = False # Controls the main connection loop (set by stop() from other thread)
        
        # These will be created in the dedicated thread's context
        self._websocket_loop = None # The dedicated asyncio event loop for this client's thread
        self._shutdown_event = None # Event to signal the asyncio loop to stop gracefully
        self._connected_event = None # Asyncio Event for connection status signaling

        self._websocket_thread = None # Reference to the thread running the WebSocket loop

        # Use asyncio.Queue for inter-task communication within the asyncio loop
        self.command_queue = asyncio.Queue() # Commands received from server for worker
        self.outgoing_ws_queue = asyncio.Queue() # Messages to send to server

        # CommandDispatcher is initialized with a reference to this async NodeClient
        self.dispatcher = CommandDispatcher(node_client_ref=self)

        self.on_node_id_invalid = on_node_id_invalid

        self._worker_task = None # To hold the asyncio task for command worker
        self._sender_task = None # To hold the asyncio task for websocket sender

        logger.info(f"NodeClient initialized for node {self.node_id}.")

    async def is_connected(self):
        """
        Checks if the WebSocket connection to the Relay server is currently active.
        This is an async method, as it relies on asyncio.Event.
        """
        # Ensure events are initialized before trying to wait on them
        if self._connected_event is None:
            return False

        # Wait a very short moment for the event to be potentially set/cleared by the loop.
        # This prevents blocking if the loop isn't running or the event isn't set immediately.
        try:
            await asyncio.wait_for(self._connected_event.wait(), timeout=0.1)
        except asyncio.TimeoutError:
            pass # Event not set within timeout, proceed to check status
        
        # Check if the event is set AND if the websocket instance is valid and not closed.
        return self._connected_event.is_set() and self._ws is not None and not self._ws.closed

    async def _on_message(self, message):
        """
        Internal handler for incoming WebSocket messages.
        This replaces the old on_message callback.
        """
        try:
            data = json.loads(message)
            msg_type = data.get('type')
            
            request_id = data.get('command', {}).get('requestId') # For commands received from the server
            
            logger.info(f"NodeClient: Received message type '{msg_type}' (Req ID: {request_id or 'N/A'}).")

            if msg_type == 'command':
                command_data = data.get('command')
                if command_data:
                    logger.info(f"NodeClient: Received command (Req ID: {command_data.get('requestId')}). Queuing for worker.")
                    await self.command_queue.put(command_data) # Put command into asyncio queue
                else:
                    logger.warning(f"NodeClient: Received 'command' type message without 'command' data: {message}")
            elif msg_type == 'node_status_check':
                logger.info("NodeClient: Received node_status_check from server. Sending pong.")
                await self._send_command_response("N/A", "PONG", {"message": "Client is alive."})
            elif msg_type == 'send_file_to_node':
                file_info = data.get('file', {})
                request_id = file_info.get('requestId') or file_info.get('request_id')
                filename = file_info.get('filename')
                file_content_b64 = file_info.get('file_content')

                if not (request_id and filename and file_content_b64):
                    logger.error(f"NodeClient: Malformed 'send_file_to_node' message: {file_info}")
                    await self._send_command_response(request_id, "error", error_message="Malformed file transfer message from server.")
                    return

                try:
                    decoded_content = base64.b64decode(file_content_b64)
                    save_path = os.path.join(self.download_dir, filename)
                    os.makedirs(os.path.dirname(save_path), exist_ok=True)
                    with open(save_path, "wb") as f:
                        f.write(decoded_content)
                    logger.info(f"NodeClient: Successfully received and saved file '{filename}' to '{save_path}'.")
                    await self._send_command_response(request_id, "success", response_payload={
                        "message": f"File '{filename}' received and saved.",
                        "local_path": save_path,
                        "file_size": len(decoded_content)
                    })
                except Exception as e:
                    logger.exception(f"NodeClient: Error processing file transfer from server for requestId {request_id}: {e}")
                    await self._send_command_response(request_id, "error", error_message=f"Error saving file from server: {str(e)}")
            else:
                logger.warning(f"NodeClient: Received unknown message type: {msg_type}")
        except json.JSONDecodeError:
            logger.error(f"NodeClient: Failed to decode JSON from WS message: {message[:100]}...")
        except Exception as e:
            logger.exception(f"NodeClient: Error in _on_message handler: {e}")

    async def _command_worker(self):
        """Asynchronous worker to process commands from the queue."""
        logger.info("NodeClient: Command worker task started.")
        while self._running and not (self._shutdown_event and self._shutdown_event.is_set()): # Check if _shutdown_event is not None
            command_data = None
            try:
                command_data = await self.command_queue.get()

                command_type = command_data.get('commandType', 'N/A')
                request_id = command_data.get('requestId')

                logger.info(f"NodeClient: Worker processing command: {command_type} (Req ID: {request_id})")

                result_from_dispatcher = await asyncio.to_thread(self.dispatcher.execute_command, command_data)

                await self._send_command_response(
                    request_id=result_from_dispatcher.get('requestId', request_id),
                    status=result_from_dispatcher.get('status', 'ERROR'),
                    response_payload=result_from_dispatcher.get('response', {}),
                    error_message=result_from_dispatcher.get('message') if result_from_dispatcher.get('status') == 'error' else None,
                    traceback=result_from_dispatcher.get('traceback')
                )

            except asyncio.CancelledError:
                logger.info("NodeClient: Command worker task cancelled.")
                break
            except Exception as e:
                logger.exception(f"NodeClient: Critical error in command worker task for Req ID {request_id if 'request_id' in locals() else 'UNKNOWN'}: {e}")
                current_request_id = command_data.get('requestId') if command_data is not None else 'UNKNOWN'
                await self._send_command_response(
                    current_request_id,
                    "ERROR",
                    error_message=f"Internal client processing error: {str(e)}",
                    traceback=traceback.format_exc()
                )
            finally:
                if command_data is not None:
                    self.command_queue.task_done()

        logger.info("NodeClient: Command worker task stopped.")

    async def _websocket_sender(self):
        """Asynchronous worker to send messages from the outgoing queue."""
        logger.info("NodeClient: WebSocket sender task started.")
        while self._running and not (self._shutdown_event and self._shutdown_event.is_set()): # Check if _shutdown_event is not None
            message_to_send = None
            try:
                message_to_send = await self.outgoing_ws_queue.get()
                if self._ws and not self._ws.closed:
                    await self._ws.send(json.dumps(message_to_send))
                    logger.debug(f"NodeClient: Sent WS message type: {message_to_send.get('type')}, Req ID: {message_to_send.get('response', {}).get('requestId')}")
                else:
                    logger.warning("NodeClient: WebSocket not connected, re-queuing message for later.")
                    await self.outgoing_ws_queue.put(message_to_send)
                    await asyncio.sleep(1)
                self.outgoing_ws_queue.task_done()
            except asyncio.CancelledError:
                logger.info("NodeClient: WebSocket sender task cancelled.")
                break
            except asyncio.QueueEmpty:
                await asyncio.sleep(0.1)
                continue
            except Exception as e:
                logger.exception(f"NodeClient: Error in WebSocket sender task: {e}")
        logger.info("NodeClient: WebSocket sender task stopped.")

    async def send_outgoing_ws_message(self, message):
        """Puts a message onto the outgoing WebSocket queue."""
        await self.outgoing_ws_queue.put(message)

    async def _send_command_response(self, request_id, status, response_payload=None, error_message=None, traceback=None):
        """
        Sends a standard command response to the Relay Server via WebSocket.
        """
        response_message = {
            "type": "node_response",
            "response": {
                "requestId": request_id,
                "status": status,
                "responsePayload": response_payload if response_payload is not None else {},
                "error": error_message,
                "traceback": traceback,
                "node_id": self.node_id,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        }
        await self.send_outgoing_ws_message(response_message)
        logger.info(f"NodeClient: Queued response for requestId '{request_id}' with status '{status}'.")

    async def send_file_to_relay(self, file_path, request_id, metadata=None):
        """
        Sends a file from the RPA client to the Django Relay Server via WebSocket.
        This method is called by the CommandDispatcher when a command instructs
        the client to upload a file as a response.
        """
        if not os.path.exists(file_path):
            logger.error(f"NodeClient: File not found for upload: {file_path}")
            await self._send_command_response(request_id, "error", error_message=f"File not found: {file_path}")
            return False
        
        if not os.path.isfile(file_path):
            logger.error(f"NodeClient: Path is not a file: {file_path}")
            await self._send_command_response(request_id, "error", error_message=f"Path is not a file: {file_path}")
            return False

        try:
            with open(file_path, "rb") as f:
                file_content = f.read()
            encoded_content = base64.b64encode(file_content).decode('utf-8')
            file_name = os.path.basename(file_path)
            file_size = os.path.getsize(file_path)

            file_details_payload = {
                "request_id": request_id,
                "node_id": self.node_id,
                "filename": file_name,
                "file_size": file_size,
                "file_content_base64": encoded_content,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "metadata": metadata if metadata is not None else {"description": f"File uploaded from RPA node {self.node_id}"}
            }

            response_message = {
                "type": "node_response",
                "response": {
                    "requestId": request_id,
                    "status": "file_upload_complete",
                    "message": f"File '{file_name}' uploaded.",
                    "node_id": self.node_id,
                    "file_details": file_details_payload
                }
            }
            
            await self.send_outgoing_ws_message(response_message)
            logger.info(f"NodeClient: Queued file '{file_name}' for upload to Relay Server via WebSocket for Req ID: {request_id}.")
            return True
        except Exception as e:
            logger.exception(f"NodeClient: An unexpected error occurred during file upload preparation: {e}")
            await self._send_command_response(request_id, "error", error_message=f"Error preparing file for upload: {str(e)}")
            return False

    async def _actual_connect_loop(self):
        """
        Establishes and manages the WebSocket connection to the Relay server.
        This is the main asynchronous loop for the NodeClient's connection.
        """
        logger.info(f"NodeClient: Starting actual connection loop to: {self.server_url}")

        # Construct the URL with the token as a query parameter
        # This is the workaround for the 'extra_headers' TypeError
        token_url = f"{self.server_url}?token={self.access_token}"

        while self._running and not (self._shutdown_event and self._shutdown_event.is_set()): # Check if _shutdown_event is not None
            try:
                logger.info(f"NodeClient: Connecting to {token_url}...")
                async with websockets.connect(
                    token_url, # Use the URL with the token
                    # extra_headers={'Authorization': f'Bearer {self.access_token}'}, # REMOVED: Causes TypeError
                    open_timeout=10, # Timeout for connection establishment
                    close_timeout=5,  # Timeout for graceful close
                    ping_interval=20, # Send ping every 20 seconds
                    ping_timeout=10   # Close connection if pong not received within 10 seconds
                ) as websocket:
                    self._ws = websocket
                    logger.info(f"NodeClient: WebSocket connected to {self.server_url}.")
                    self._connected_event.set() # Signal that connection is established

                    self._worker_task = asyncio.create_task(self._command_worker())
                    self._sender_task = asyncio.create_task(self._websocket_sender())

                    initial_request_id = str(uuid.uuid4())
                    initial_metadata_payload = {
                        "type": "node_response",
                        "response": {
                            "requestId": initial_request_id,
                            "status": "node_connected",
                            "message": "Node client connected and sent initial metadata.",
                            "responsePayload": {
                                "node_id": self.node_id,
                                "metadata": self.initial_metadata
                            },
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "node_id": self.node_id
                        }
                    }
                    await self._ws.send(json.dumps(initial_metadata_payload))
                    logger.info(f"NodeClient: Sent initial node metadata (Req ID: {initial_request_id}).")

                    while not self._ws.closed and self._running and not (self._shutdown_event and self._shutdown_event.is_set()): # Check if _shutdown_event is not None
                        try:
                            message = await asyncio.wait_for(self._ws.recv(), timeout=60)
                            await self._on_message(message)
                        except asyncio.TimeoutError:
                            logger.debug("NodeClient: No message received for 60 seconds. (Ping/pong handled by websockets library).")
                            continue
                        except websockets.exceptions.ConnectionClosed:
                            logger.info("NodeClient: Connection closed by peer during recv().")
                            break
                        except Exception as e:
                            logger.exception(f"NodeClient: Error during message receive/process: {e}. Breaking inner loop.")
                            break

            except websockets.exceptions.ConnectionClosedOK:
                logger.info("NodeClient: WebSocket connection closed gracefully.")
            except websockets.exceptions.ConnectionClosedError as e:
                logger.warning(f"NodeClient: WebSocket connection closed with error: {e}. Retrying...")
            except asyncio.TimeoutError:
                logger.warning("NodeClient: Connection attempt timed out. Retrying...")
            except OSError as e:
                logger.error(f"NodeClient: Network/OS error during connection: {e}. Retrying...")
            except Exception as e:
                logger.exception(f"NodeClient: Unexpected error during WebSocket connection: {e}. Retrying...")
            finally:
                self._ws = None
                if self._connected_event: # Only clear if initialized
                    self._connected_event.clear()

                if self._worker_task and not self._worker_task.done():
                    self._worker_task.cancel()
                    try: await self._worker_task
                    except asyncio.CancelledError: pass
                
                if self._sender_task and not self._sender_task.done():
                    self._sender_task.cancel()
                    try: await self._sender_task
                    except asyncio.CancelledError: pass

                while not self.command_queue.empty():
                    try: await self.command_queue.get()
                    except Exception: pass # Handle potential error if queue item is not awaitable after loop close
                while not self.outgoing_ws_queue.empty():
                    try: await self.outgoing_ws_queue.get()
                    except Exception: pass # Handle potential error if queue item is not awaitable after loop close

                if self._running and self._shutdown_event and not self._shutdown_event.is_set(): # Check if _shutdown_event is not None
                    logger.info("NodeClient: Waiting 5 seconds before attempting to reconnect...")
                    try:
                        await asyncio.wait_for(self._shutdown_event.wait(), timeout=5)
                        break
                    except asyncio.TimeoutError:
                        pass

        logger.info("NodeClient: Main connection loop terminated.")


    def _run_websocket_loop(self):
        """
        Target function for the NodeClient's dedicated thread.
        Initializes and runs its own asyncio event loop.
        """
        logger.info("NodeClient: Starting new WebSocket event loop in separate thread.")
        self._websocket_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._websocket_loop)

        self._shutdown_event = asyncio.Event()
        self._connected_event = asyncio.Event() # Create asyncio.Event objects within THIS loop's context

        try:
            self._websocket_loop.run_until_complete(self._actual_connect_loop())
        except Exception as e:
            logger.critical(f"NodeClient: Unhandled exception in main WebSocket connection loop: {e}", exc_info=True)
        finally:
            if self._websocket_loop and not self._websocket_loop.is_closed():
                pending_tasks = asyncio.all_tasks(self._websocket_loop)
                for task in pending_tasks:
                    task.cancel()
                    try:
                        self._websocket_loop.run_until_complete(asyncio.wait_for(task, timeout=1.0))
                    except (asyncio.CancelledError, asyncio.TimeoutError):
                        pass
                    except Exception as e:
                        logger.error(f"NodeClient: Error cancelling task during loop shutdown: {e}")

                self._websocket_loop.run_until_complete(self._websocket_loop.shutdown_asyncgens())
                self._websocket_loop.close()
                logger.info("NodeClient: WebSocket event loop closed.")
            else:
                logger.info("NodeClient: WebSocket event loop was already closed or not initialized.")
            
            self._websocket_loop = None
            self._shutdown_event = None
            self._connected_event = None
            logger.info("NodeClient: _run_websocket_loop method finished.")

    def connect(self):
        """
        Synchronous entry point to start the NodeClient's WebSocket connection
        and message handling loop in a new, dedicated thread.
        """
        if self._running and self._websocket_thread and self._websocket_thread.is_alive():
            logger.warning("NodeClient is already running.")
            return

        self._running = True
        self._websocket_thread = threading.Thread(target=self._run_websocket_loop, daemon=True)
        self._websocket_thread.start()
        logger.info("NodeClient: Started connection thread.")

    def stop(self):
        """
        Gracefully stops the NodeClient, signaling its dedicated thread to shut down.
        This method is called from a different thread (main.py's thread).
        """
        logger.info("NodeClient: Stopping NodeClient.")
        
        if not self._running and (self._websocket_thread is None or not self._websocket_thread.is_alive()):
            logger.info("NodeClient: Agent is not running or not initialized, no need to stop.")
            return

        self._running = False

        if self._websocket_loop and not self._websocket_loop.is_closed():
            if self._shutdown_event:
                try:
                    asyncio.run_coroutine_threadsafe(self._shutdown_event.set(), self._websocket_loop).result(timeout=1)
                    logger.debug("NodeClient: Signaled shutdown event to its loop.")
                except asyncio.TimeoutError:
                    logger.warning("NodeClient: Timeout waiting for shutdown event to set on its loop.")
                except Exception as e:
                    logger.error(f"NodeClient: Error scheduling shutdown event set: {e}")
            else:
                logger.warning("NodeClient: _shutdown_event is None, cannot signal graceful shutdown to loop.")

            if self._ws and not self._ws.closed:
                logger.debug("NodeClient: Attempting to schedule WebSocket close from stop().")
                try:
                    async def _close_ws_coroutine():
                        if self._ws and not self._ws.closed:
                            await self._ws.close()
                    asyncio.run_coroutine_threadsafe(_close_ws_coroutine(), self._websocket_loop).result(timeout=5)
                    logger.info("NodeClient: WebSocket graceful close scheduled and completed from stop().")
                except asyncio.TimeoutError:
                    logger.warning("NodeClient: Timeout waiting for WebSocket to close from stop().")
                except Exception as e:
                    logger.error(f"NodeClient: Error during WebSocket close scheduling from stop(): {e}")
                finally:
                    self._ws = None

            if self._connected_event: # Only clear if initialized
                self._connected_event.clear()

            if self._websocket_thread and self._websocket_thread.is_alive():
                logger.info("NodeClient: Waiting for NodeClient thread to finish...")
                self._websocket_thread.join(timeout=10)
                if self._websocket_thread.is_alive():
                    logger.warning("NodeClient: NodeClient thread did not stop gracefully within timeout.")
                else:
                    logger.info("NodeClient: NodeClient thread finished.")
            self._websocket_thread = None
        else:
            logger.warning("NodeClient: WebSocket loop not running or already closed when stop() called.")
            if self._connected_event: # Only clear if initialized
                self._connected_event.clear()

        logger.info("NodeClient: NodeClient stopped.")