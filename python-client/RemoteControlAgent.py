# File: python-client/RemoteControlAgent.py

import asyncio
import websockets
import json
import base64
import time
import logging
from datetime import datetime, timezone
import threading
import io

# --- Screen Capture Libraries ---
# You'll need to ensure these are installed: pip install mss Pillow
import mss
from PIL import Image

logger = logging.getLogger('RemoteControlAgent')

class RemoteControlAgent:
    def __init__(self, rc_server_ws_url, node_id, access_token, command_dispatcher_instance=None):
        """
        Initializes the RemoteControlAgent.

        Args:
            rc_server_ws_url (str): The WebSocket URL for the Remote Control server (e.g., ws://localhost:8000/ws/rc-agent/ABC123/).
            node_id (str): The unique ID of this RPA Node.
            access_token (str): The OAuth2 access token for authentication.
            command_dispatcher_instance: Reference to the main NodeClient's CommandDispatcher.
                                         This will be used to execute input commands.
        """
        self.rc_server_ws_url = rc_server_ws_url
        self.node_id = node_id
        self.access_token = access_token
        self.command_dispatcher = command_dispatcher_instance # For executing input commands

        self._ws = None # Holds the *currently active* websockets connection object (valid only within async with)
        self._running = False # Controls the main agent thread/loop
        self._streaming_active = False # Controls screenshot streaming loop

        self._stream_task = None # asyncio task for the screenshot streamer
        self._websocket_loop = None # The dedicated asyncio event loop for this agent's thread
        self._connected_event = threading.Event() # Signals connection status to main thread
        self._shutdown_event = None # Initialize as None, will be created in the dedicated loop's context

        logger.info(f"RemoteControlAgent initialized for node {self.node_id}.")

    def is_connected(self):
        """
        Checks if the WebSocket connection to the Remote Control server is currently active.
        """
        # _connected_event is set/cleared by _connect_websocket based on actual connection status
        return self._connected_event.is_set()

    async def _connect_websocket(self):
        """
        Establishes and manages the WebSocket connection.
        This is the main async loop for the agent's connection management.
        """
        full_url = f"{self.rc_server_ws_url}?token={self.access_token}"

        # Outer loop to handle continuous reconnection attempts as long as agent is supposed to be running
        while self._running and not (self._shutdown_event and self._shutdown_event.is_set()): # Check if _shutdown_event is not None
            try:
                logger.info(f"RC Agent: Attempting to connect to {full_url}")
                async with websockets.connect(full_url, open_timeout=10, close_timeout=5, ping_interval=20, ping_timeout=10) as websocket_conn:
                    self._ws = websocket_conn # Store the active connection for is_connected()

                    logger.info(f"RC Agent: WebSocket connected to {self.rc_server_ws_url}.")
                    self._connected_event.set() # Signal that connection is active

                    # Ensure previous streaming task is cancelled cleanly if connection re-established
                    if self._stream_task and not self._stream_task.done():
                        self._stream_task.cancel()
                        try:
                            await self._stream_task # Allow it to process cancellation
                        except asyncio.CancelledError:
                            logger.debug("RC Agent: Old streaming task successfully cancelled.")
                        except Exception as e:
                            logger.error(f"RC Agent: Error awaiting old streaming task after cancellation: {e}")
                    self._streaming_active = False # Reset streaming state on new connection
                    self._stream_task = None # Clear reference to old task

                    # --- Main operational phase of the connection ---
                    await self._handle_websocket_messages(websocket_conn)

            except websockets.exceptions.ConnectionClosed as e:
                logger.info(f"RC Agent: WebSocket connection closed: {e.code} - {e.reason}. Attempting reconnect...")
            except asyncio.TimeoutError: # For open_timeout
                logger.warning("RC Agent: Connection attempt timed out. Retrying...")
            except OSError as e: # Catch "No route to host", "Connection refused", etc.
                logger.error(f"RC Agent: Network/OS error during connection: {e}. Retrying...")
            except Exception as e:
                # Catch any other unexpected errors during connection establishment/management
                logger.exception(f"RC Agent: Unexpected error during WebSocket connection management: {e}. Retrying...")
            finally:
                # --- Cleanup when `async with` block exits (connection closed/failed) ---
                self._ws = None # Clear reference to the closed connection
                self._connected_event.clear() # Signal connection is no longer active
                self._streaming_active = False # Ensure streaming is off if connection drops
                if self._stream_task and not self._stream_task.done():
                    self._stream_task.cancel() # Ensure streaming task is stopped if still running
                    try:
                        await self._stream_task # Allow it to process cancellation
                    except asyncio.CancelledError:
                        logger.debug("RC Agent: Streaming task successfully cancelled during connection cleanup.")
                    except Exception as e:
                        logger.error(f"RC Agent: Error awaiting streaming task during connection cleanup: {e}")
                    self._stream_task = None # Clear reference after cancellation attempt

                # Only sleep if the agent is still meant to be running and not shutting down
                if self._running and (self._shutdown_event and not self._shutdown_event.is_set()): # Check if _shutdown_event is not None
                    logger.info("RC Agent: Waiting 5 seconds before attempting to reconnect...")
                    try:
                        # Wait, but also allow for shutdown signal during sleep
                        await asyncio.wait_for(self._shutdown_event.wait(), timeout=5)
                        # If we reached here, shutdown event was set within the timeout
                        break # Exit the connection loop
                    except asyncio.TimeoutError:
                        pass # Continue to next reconnection attempt if timeout occurs

        logger.info("RC Agent: Main connection loop terminated.")

    async def _handle_websocket_messages(self, websocket_conn):
        """
        Processes messages received from the Remote Control server for the duration of a single connection.
        This coroutine runs inside the 'async with websockets.connect' block.
        """
        logger.info("RC Agent: Started handling incoming WebSocket messages.")
        # --- DEBUG PRINTS START ---
        logger.debug(f"RC Agent: _handle_websocket_messages: Type of websocket_conn: {type(websocket_conn)}")
        logger.debug(f"RC Agent: _handle_websocket_messages: dir(websocket_conn): {dir(websocket_conn)}")
        logger.debug(f"RC Agent: _handle_websocket_messages: websocket_conn is None? {websocket_conn is None}")
        # --- DEBUG PRINTS END ---
        
        try:
            while self._running and not (self._shutdown_event and self._shutdown_event.is_set()): # Check if _shutdown_event is not None
                if websocket_conn.closed: # Explicitly check connection status within the loop
                    logger.info("RC Agent: _handle_websocket_messages: Connection is closed, exiting loop.")
                    break

                try:
                    message = await asyncio.wait_for(websocket_conn.recv(), timeout=60) # Add a timeout for recv
                except asyncio.TimeoutError:
                    logger.debug("RC Agent: No message received for 60 seconds (ping/pong handled by library).")
                    continue
                except websockets.exceptions.ConnectionClosed:
                    logger.info("RC Agent: Connection closed by peer during recv().")
                    break
                except Exception as e:
                    logger.exception(f"RC Agent: Error during message receive: {e}. Exiting handler.")
                    break # Exit on unexpected receive error

                try:
                    data = json.loads(message)
                except json.JSONDecodeError:
                    logger.error(f"RC Agent: Failed to decode JSON from message. Raw: {message[:200]}...", exc_info=True)
                    continue # Skip to next message

                msg_type = data.get('type')

                # Log full message for debug, partial for info
                if msg_type in ['remote_control_frame']: # Too verbose for INFO
                    logger.debug(f"RC Agent: Received message type '{msg_type}'.")
                else:
                    logger.info(f"RC Agent: Received message type '{msg_type}'. Raw message part: {message[:100]}...")

                if msg_type == 'control_command':
                    command_data = data.get('command', {})
                    command_type = command_data.get('commandType')
                    logger.info(f"RC Agent: Received control command: {command_type}")

                    if command_type == 'start_control':
                        if not self._streaming_active:
                            self._streaming_active = True
                            # Create task only if not already running and not done
                            if not self._stream_task or self._stream_task.done():
                                self._stream_task = self._websocket_loop.create_task(self._screenshot_streamer(websocket_conn))
                                logger.info("RC Agent: Started screenshot streaming.")
                            else:
                                logger.warning("RC Agent: Attempted to start streaming but it's already active or task exists.")
                        else:
                            logger.info("RC Agent: Streaming already active, ignoring 'start_control' command.")
                    elif command_type == 'stop_control':
                        if self._streaming_active:
                            self._streaming_active = False
                            if self._stream_task and not self._stream_task.done():
                                self._stream_task.cancel()
                                try:
                                    await self._stream_task # Allow it to process cancellation
                                except asyncio.CancelledError:
                                    logger.debug("RC Agent: Screenshot streaming task successfully cancelled by 'stop_control'.")
                                except Exception as e:
                                    logger.error(f"RC Agent: Error awaiting streaming task after 'stop_control' cancellation: {e}")
                                finally:
                                    self._stream_task = None # Clear reference
                            logger.info("RC Agent: Stopped screenshot streaming.")
                        else:
                            logger.info("RC Agent: Streaming not active, ignoring 'stop_control' command.")
                    else:
                        logger.warning(f"RC Agent: Unknown control command: {command_type}.")

                elif msg_type in ['mouse_move', 'mouse_click', 'mouse_drag', 'mouse_scroll',
                                  'key_press', 'key_combo', 'type_text', 'combo_click']:
                    
                    # Wrap the incoming RC input into the format expected by CommandDispatcher
                    command_data_for_dispatcher = {
                        "commandType": msg_type,
                        "params": data.get('params', {}),
                        "requestId": f"rc_input_local_{self.node_id}_{time.time()}" 
                    }
                    
                    logger.info(f"RC Agent: Executing RC input command: {msg_type} (local Req ID: {command_data_for_dispatcher['requestId']}).")

                    if self.command_dispatcher:
                        # Run blocking command in a thread pool to avoid blocking the asyncio loop
                        try:
                            result = await asyncio.to_thread(self.command_dispatcher.execute_command, command_data_for_dispatcher)
                            logger.debug(f"RC input command '{msg_type}' execution result: {result}.")
                        except Exception as cmd_e:
                            logger.error(f"RC Agent: Error executing RC input command '{msg_type}': {cmd_e}", exc_info=True)
                    else:
                        logger.error(f"RC Agent: CommandDispatcher not provided. Cannot execute RC input command '{msg_type}'.")
                
                else:
                    logger.warning(f"RC Agent: Received unhandled message type '{msg_type}'. Raw: {message[:100]}...")

        except websockets.exceptions.ConnectionClosed:
            logger.info("RC Agent: _handle_websocket_messages: Connection closed, exiting loop.")
        except Exception as e:
            logger.exception(f"RC Agent: Unhandled error in _handle_websocket_messages: {e}.")
            raise # Re-raise to be caught by _connect_websocket's try/except for reconnection logic

        logger.info("RC Agent: Exiting incoming WebSocket message handler loop.")


    async def _screenshot_streamer(self, websocket_conn):
        """Continuously captures screenshots and sends them to the RC server."""
        logger.info("RC Agent: _screenshot_streamer task started.")
        monitor_number = 1 # 0 for all monitors, 1 for primary monitor (adjust as needed)
        capture_interval = 0.25 # Seconds (e.g., 0.25s for ~4 FPS)
        sct = mss.mss() # Initialize mss for screen capturing

        # Ensure that monitor_number is valid
        if monitor_number >= len(sct.monitors):
            logger.error(f"RC Agent: Invalid monitor number {monitor_number}. Available monitors: {len(sct.monitors)}. Defaulting to primary (1).")
            monitor_number = 1 if len(sct.monitors) > 1 else 0 # Fallback to 1st available

        while self._streaming_active and not websocket_conn.closed and not (self._shutdown_event and self._shutdown_event.is_set()): # Check if _shutdown_event is not None
            try:
                # Check connection status more frequently
                if websocket_conn.closed:
                    logger.warning("RC Agent: Streamer: WebSocket is closed. Stopping stream loop.")
                    self._streaming_active = False # Signal loop termination
                    break

                sct_img = sct.grab(sct.monitors[monitor_number])
                img_buffer = io.BytesIO()
                # Ensure the image is in RGB mode for JPEG saving if it comes in RGBA
                img = Image.frombytes("RGB", sct_img.size, sct_img.rgb)
                img.save(img_buffer, format="JPEG", quality=70)
                
                image_base64 = base64.b64encode(img_buffer.getvalue()).decode('utf-8')

                payload = {
                    "type": "remote_control_frame",
                    "image_base64": image_base64,
                    "timestamp": datetime.now(timezone.utc).isoformat(), # Use timezone-aware datetime for consistency
                    "node_id": self.node_id # Include node_id for server routing/logging
                }
                
                # Use a try-except for sending to catch connection issues immediately
                try:
                    await websocket_conn.send(json.dumps(payload))
                    logger.debug(f"RC Agent: Sent frame for node {self.node_id}. Frame size: {len(image_base64)} bytes.")
                except websockets.exceptions.ConnectionClosed as e:
                    logger.warning(f"RC Agent: Streamer: Failed to send frame, connection closed: {e}. Stopping stream.")
                    self._streaming_active = False
                    break
                except Exception as send_e:
                    logger.error(f"RC Agent: Streamer: Error sending frame: {send_e}. Stopping stream.", exc_info=True)
                    self._streaming_active = False
                    break

                await asyncio.sleep(capture_interval)

            except asyncio.CancelledError:
                logger.info("RC Agent: Screenshot streamer task cancelled gracefully.")
                break # Exit loop if task is cancelled
            except mss.exception.ScreenShotError as e:
                logger.error(f"RC Agent: Screenshot capture error: {e}. Stopping stream due to error.")
                self._streaming_active = False # Stop streaming on capture error
                break
            except Exception as e:
                logger.exception(f"RC Agent: Unexpected error in screenshot streamer: {e}. Stopping stream.")
                self._streaming_active = False # Stop streaming on unexpected error
                break
        logger.info("RC Agent: _screenshot_streamer task finished.")

    def start(self):
        """
        Starts the RemoteControlAgent's WebSocket connection and message handling loop
        in a new asyncio event loop for this thread.
        """
        if self._running:
            logger.warning("RemoteControlAgent is already running.")
            return

        self._running = True
        self._websocket_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._websocket_loop)

        # IMPORTANT: Create the shutdown event in THIS loop's context
        self._shutdown_event = asyncio.Event()

        # Run the main connection coroutine until the shutdown event is set
        logger.info("RC Agent: Starting WebSocket connection loop...")
        try:
            self._websocket_loop.run_until_complete(self._connect_websocket())
        except Exception as e:
            logger.critical(f"RC Agent: Unhandled exception in main WebSocket connection loop: {e}", exc_info=True)
        finally:
            # Clean up the loop after it stops running
            if self._websocket_loop and not self._websocket_loop.is_closed():
                # Cancel all remaining tasks in the loop
                pending_tasks = asyncio.all_tasks(self._websocket_loop)
                for task in pending_tasks:
                    task.cancel()
                    try:
                        # Give tasks a moment to process cancellation
                        self._websocket_loop.run_until_complete(asyncio.wait_for(task, timeout=1.0))
                    except (asyncio.CancelledError, asyncio.TimeoutError):
                        pass # Expected
                    except Exception as e:
                        logger.error(f"RC Agent: Error cancelling task during loop shutdown: {e}")

                # This is important for clean shutdown:
                self._websocket_loop.run_until_complete(self._websocket_loop.shutdown_asyncgens())
                self._websocket_loop.close()
                logger.info("RC Agent: WebSocket event loop closed.")
            else:
                logger.info("RC Agent: WebSocket event loop was already closed.")
            
            # Clear references after cleanup
            self._websocket_loop = None
            self._shutdown_event = None
        logger.info("RC Agent: RemoteControlAgent 'start' method finished.")

    def stop(self):
        """
        Gracefully stops the RemoteControlAgent, signaling its dedicated thread to shut down.
        This is called from the main thread, so it must interact with the agent's loop safely.
        """
        logger.info("RC Agent: Stopping RemoteControlAgent.")
        
        # Check if agent was even started properly before attempting to stop
        if not self._running and (self._websocket_loop is None or self._websocket_loop.is_closed()):
            logger.info("RC Agent: Agent is not running or not initialized, no need to stop.")
            return

        self._running = False # Signal the main connection loop to terminate
        self._streaming_active = False # Signal streaming loop to terminate

        if self._websocket_loop and not self._websocket_loop.is_closed():
            if self._shutdown_event: # Check if event exists before trying to set
                # Set the shutdown event to signal async tasks to terminate.
                # Use call_soon_threadsafe to schedule this on the agent's loop from the current thread.
                try:
                    self._websocket_loop.call_soon_threadsafe(self._shutdown_event.set)
                    logger.debug("RC Agent: Signaled shutdown event to its loop.")
                except Exception as e:
                    logger.error(f"RC Agent: Error scheduling shutdown event set: {e}")
            else:
                logger.warning("RC Agent: _shutdown_event is None, cannot signal graceful shutdown.")

            # Attempt to cancel the streaming task if it's still running
            if self._stream_task and not self._stream_task.done():
                logger.debug("RC Agent: Attempting to schedule streaming task cancellation from stop().")
                try:
                    self._websocket_loop.call_soon_threadsafe(self._stream_task.cancel)
                    # We don't await here directly; the _connect_websocket's finally block handles awaiting
                except Exception as e:
                    logger.error(f"RC Agent: Error scheduling streaming task cancellation: {e}")
                finally:
                    self._stream_task = None # Clear task reference

            # Close the WebSocket connection gracefully
            if self._ws and not self._ws.closed:
                logger.debug("RC Agent: Attempting to schedule WebSocket close from stop().")
                try:
                    async def _close_ws_coroutine():
                        if self._ws and not self._ws.closed: # Double check inside coroutine
                            await self._ws.close()
                    # Schedule the close coroutine to run on the agent's loop
                    self._websocket_loop.call_soon_threadsafe(
                        lambda: asyncio.create_task(_close_ws_coroutine())
                    )
                    logger.info("RC Agent: WebSocket graceful close scheduled from stop().")
                except Exception as e:
                    logger.error(f"RC Agent: Error scheduling WebSocket close: {e}")
                finally:
                    self._ws = None # Clear reference

            self._connected_event.clear() # Ensure connection status is cleared

            # The _connect_websocket loop running in the dedicated thread should now exit
            # due to self._running=False and _shutdown_event being set.
            # The finally block in `start` will handle the actual loop cleanup.
        else:
            logger.warning("RC Agent: WebSocket loop not running or already closed during stop().")
            self._connected_event.clear() # Ensure event is cleared even if loop isn't active

        logger.info("RC Agent: RemoteControlAgent stopped.")