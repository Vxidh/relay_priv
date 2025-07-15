# File: commands/system.py

import time
import os
import base64
import io
import subprocess
import logging
import pyautogui  
import uuid  
import webbrowser
import requests
import traceback
from .utils import normalize_path  
log = logging.getLogger(__name__)

class SystemCommands:
    def __init__(self, node_client_ref=None):
        self.node_client = node_client_ref
        if self.node_client and hasattr(self.node_client, 'download_dir'):
            self.download_dir = self.node_client.download_dir
        else:
            self.download_dir = os.path.join(os.getcwd(), 'rpa_client_downloads')
        os.makedirs(self.download_dir, exist_ok=True)

    def _normalize_param_path(self, params, key):
        """Normalizes a path parameter in the params dictionary."""
        if key in params and isinstance(params[key], str):
            params[key] = normalize_path(params[key])

    def ping(self, params):
        request_id = params.get('requestId')
        log.info(f"[System] Executing ping. RequestId: {request_id}")
        return {
            "status": "success",
            "action": "ping",
            "timestamp": time.time(),
            "message": "pong",
            "requestId": request_id # Explicitly include requestId
        }

    def wait(self, params):
        request_id = params.get('requestId')
        duration_seconds = params.get("durationSeconds", 0) # Use "durationSeconds" for consistency with other params
        log.info(f"[System] Executing wait command for {duration_seconds} seconds. RequestId: {request_id}")
        try:
            time.sleep(duration_seconds)
            return {
                "status": "success",
                "action": "wait",
                "message": f"Waited for {duration_seconds} seconds.",
                "requestId": request_id
            }
        except Exception as e:
            log.error(f"[System] Wait command error for Req ID: {request_id}: {e}", exc_info=True)
            return {
                "status": "error",
                "action": "wait",
                "message": f"Error during wait: {str(e)}",
                "traceback": traceback.format_exc(),
                "requestId": request_id
            }

    def screenshot(self, params):
        request_id = params.get('requestId')
        log.info(f"[System] Capturing screenshot. RequestId: {request_id}")
        try:
            screenshot_bytes = io.BytesIO()
            pyautogui.screenshot().save(screenshot_bytes, format='PNG')
            base64_image = base64.b64encode(screenshot_bytes.getvalue()).decode('utf-8')
            
            # The 'file_upload' message type is handled directly by the NodeConsumer on the Relay Server.
            # This allows sending large binary data outside the standard command response.
            file_upload_message = {
                "type": "file_upload",
                "file": {
                    "request_id": request_id,
                    "filename": f"screenshot_{uuid.uuid4().hex}.png",
                    "file_content": base64_image, # This is 'file_content'
                    "mime_type": "image/png",
                    "uploaded_by_node_id": self.node_client.node_id if self.node_client else "unknown_node"
                }
            }
            
            if self.node_client and hasattr(self.node_client, 'outgoing_ws_queue'):
                self.node_client.outgoing_ws_queue.put(file_upload_message)
                log.info(f"[System] Screenshot captured and queued for upload. RequestId: {request_id}")
                return {
                    "status": "success",
                    "action": "screenshot",
                    "message": "Screenshot captured and queued for upload.",
                    "requestId": request_id
                }
            else:
                log.error(f"[System] Failed to queue screenshot for upload for Req ID: {request_id}: NodeClient or queue not ready.")
                return {
                    "status": "error",
                    "action": "screenshot",
                    "message": "Failed to queue screenshot for upload: Client not ready.",
                    "requestId": request_id
                }
        except Exception as e:
            log.error(f"[System] Screenshot error for Req ID: {request_id}: {e}", exc_info=True)
            return {
                "status": "error",
                "action": "screenshot",
                "message": str(e) or "Unhandled exception",
                "traceback": traceback.format_exc(),
                "requestId": request_id
            }

    def get_screen_size(self, params):
        request_id = params.get('requestId')
        log.info(f"[System] Getting screen size. RequestId: {request_id}")
        try:
            width, height = pyautogui.size()
            return {
                "status": "success",
                "action": "get_screen_size",
                "width": width,
                "height": height,
                "requestId": request_id
            }
        except Exception as e:
            log.error(f"[System] get_screen_size error for Req ID: {request_id}: {e}", exc_info=True)
            return {
                "status": "error",
                "action": "get_screen_size",
                "message": str(e) or "Unhandled exception",
                "traceback": traceback.format_exc(),
                "requestId": request_id
            }

    def open_url(self, params):
        request_id = params.get('requestId')
        url = params.get("url")
        log.info(f"[System] Opening URL: {url}. RequestId: {request_id}")
        try:
            if not url:
                raise ValueError("URL parameter is missing.")
            webbrowser.open(url)
            return {
                "status": "success",
                "action": "open_url",
                "url": url,
                "requestId": request_id
            }
        except Exception as e:
            log.error(f"[System] open_url error for Req ID: {request_id}: {e}", exc_info=True)
            return {
                "status": "error",
                "action": "open_url",
                "message": str(e) or "Unhandled exception",
                "traceback": traceback.format_exc(),
                "requestId": request_id
            }

    def read_file(self, params):
        request_id = params.get('requestId')
        self._normalize_param_path(params, "filePath")
        file_path = params.get("filePath")
        encoding = params.get("encoding", "utf-8")
        log.info(f"[System] Reading file: {file_path}. RequestId: {request_id}")
        try:
            if not file_path:
                raise ValueError("filePath parameter is missing.")
            if not os.path.exists(file_path):
                raise FileNotFoundError(f"File not found: {file_path}")
            if not os.path.isfile(file_path):
                raise ValueError(f"Path is not a file: {file_path}")

            with open(file_path, 'r', encoding=encoding) as f:
                content = f.read()
            return {
                "status": "success",
                "action": "read_file",
                "filePath": file_path,
                "content": content,
                "requestId": request_id
            }
        except Exception as e:
            log.error(f"[System] read_file error for Req ID: {request_id}: {e}", exc_info=True)
            return {
                "status": "error",
                "action": "read_file",
                "message": str(e) or "Unhandled exception",
                "traceback": traceback.format_exc(),
                "requestId": request_id
            }

    def write_file(self, params):
        request_id = params.get('requestId')
        self._normalize_param_path(params, "filePath")
        file_path = params.get("filePath")
        content = params.get("content")
        encoding = params.get("encoding", "utf-8")
        mode = params.get("mode", "w") # 'w' for write, 'a' for append
        log.info(f"[System] Writing to file: {file_path} (Mode: {mode}). RequestId: {request_id}")
        try:
            if not (file_path and content is not None):
                raise ValueError("filePath or content parameter is missing.")
            
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, mode, encoding=encoding) as f:
                f.write(content)
            return {
                "status": "success",
                "action": "write_file",
                "filePath": file_path,
                "requestId": request_id
            }
        except Exception as e:
            log.error(f"[System] write_file error for Req ID: {request_id}: {e}", exc_info=True)
            return {
                "status": "error",
                "action": "write_file",
                "message": str(e) or "Unhandled exception",
                "traceback": traceback.format_exc(),
                "requestId": request_id
            }

    def download_file(self, params):
        request_id = params.get('requestId')
        self._normalize_param_path(params, "destinationPath")
        url = params.get("url")
        destination_path = params.get("destinationPath")
        log.info(f"[System] Downloading file from {url} to {destination_path}. RequestId: {request_id}")
        try:
            if not (url and destination_path):
                raise ValueError("URL or destinationPath parameter is missing.")

            response = requests.get(url, stream=True)
            response.raise_for_status() # Raise an exception for bad status codes (4xx or 5xx)
            
            os.makedirs(os.path.dirname(destination_path), exist_ok=True)
            with open(destination_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            return {
                "status": "success",
                "action": "download_file",
                "url": url,
                "destinationPath": destination_path,
                "requestId": request_id
            }
        except requests.exceptions.RequestException as e:
            log.error(f"[System] download_file HTTP error for Req ID: {request_id}: {e}", exc_info=True)
            return {
                "status": "error",
                "action": "download_file",
                "message": f"HTTP Error: {str(e)}",
                "traceback": traceback.format_exc(),
                "requestId": request_id
            }
        except Exception as e:
            log.error(f"[System] download_file error for Req ID: {request_id}: {e}", exc_info=True)
            return {
                "status": "error",
                "action": "download_file",
                "message": str(e) or "Unhandled exception",
                "traceback": traceback.format_exc(),
                "requestId": request_id
            }

    def upload_file(self, params):
        """
        Uploads a file by sending its base64 encoded content via the WebSocket
        to the Relay Server. This replaces the HTTP POST upload mechanism.
        """
        request_id = params.get('requestId')
        self._normalize_param_path(params, "filePath")
        file_path = params.get("filePath")
        log.info(f"[System] Uploading file {file_path} via WebSocket. RequestId: {request_id}")
        try:
            if not file_path:
                raise ValueError("filePath parameter is missing.")
            if not os.path.exists(file_path):
                raise FileNotFoundError(f"File not found: {file_path}")
            if not os.path.isfile(file_path):
                raise ValueError(f"Path is not a file: {file_path}")

            with open(file_path, 'rb') as f:
                encoded_content = base64.b64encode(f.read()).decode('utf-8')
            
            filename = os.path.basename(file_path)
            file_size = os.path.getsize(file_path)

            file_upload_message = {
                "type": "file_upload", # This type is handled by the Relay Consumer
                "file": {
                    "request_id": request_id,
                    "filename": filename,
                    "file_content": encoded_content, # This is 'file_content'
                    "mime_type": "image/png", # Changed to 'image/png' if it's a screenshot
                    "uploaded_by_node_id": self.node_client.node_id if self.node_client else "unknown_node",
                    "file_size": file_size,
                    "original_command_type": "upload_file" # Add context
                }
            }
            
            if self.node_client and hasattr(self.node_client, 'outgoing_ws_queue'):
                self.node_client.outgoing_ws_queue.put(file_upload_message)
                log.info(f"[System] File '{filename}' content queued for WebSocket upload. RequestId: {request_id}")
                return {
                    "status": "success",
                    "action": "upload_file",
                    "message": f"File '{filename}' content queued for WebSocket upload.",
                    "filePath": file_path,
                    "fileName": filename,
                    "fileSize": file_size,
                    "requestId": request_id
                }
            else:
                log.error(f"[System] upload_file: WebSocket queue unavailable for Req ID: {request_id}.")
                return {
                    "status": "error",
                    "action": "upload_file",
                    "message": "WebSocket queue unavailable for file transfer.",
                    "requestId": request_id
                }
        except Exception as e:
            log.error(f"[System] upload_file error for Req ID: {request_id}: {e}", exc_info=True)
            return {
                "status": "error",
                "action": "upload_file",
                "message": str(e) or "Unhandled exception",
                "traceback": traceback.format_exc(),
                "requestId": request_id
            }

    def receive_file(self, params):
        request_id = params.get('requestId')
        # Ensure filename is normalized BEFORE joining with download_dir
        filename = params.get('filename')
        # MODIFIED: Changed from 'file_content' to 'file_content_base64' to match Java
        file_content_base64 = params.get('file_content_base64') 
        
        log.info(f"[System] Receiving file: {filename}. RequestId: {request_id}")
        log.debug(f"[System] receive_file - Raw params: {params}")
        log.debug(f"[System] receive_file - Extracted filename: {filename}")
        log.debug(f"[System] receive_file - Extracted file_content_base64 (truncated): {file_content_base64[:50] if file_content_base64 else 'None'}")


        try:
            if not (filename and file_content_base64):
                raise ValueError("filename or file_content_base64 parameter is missing.") # Updated error message

            # Normalize the filename to prevent directory traversal within the download directory
            safe_filename = normalize_path(filename)
            file_path = os.path.join(self.download_dir, safe_filename)
            
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            decoded_content = base64.b64decode(file_content_base64)
            with open(file_path, 'wb') as f:
                f.write(decoded_content)
            
            return {
                "status": "success",
                "action": "receive_file",
                "saved_path": file_path,
                "requestId": request_id
            }
        except Exception as e:
            log.error(f"[System] receive_file error for Req ID: {request_id}: {e}", exc_info=True)
            return {
                "status": "error",
                "action": "receive_file",
                "message": str(e) or "Unhandled exception",
                "traceback": traceback.format_exc(),
                "requestId": request_id
            }

    def run_shell_command(self, params):
        request_id = params.get('requestId')
        command = params.get("command")
        timeout = params.get("timeout", 60) # Add timeout for shell commands
        log.info(f"[System] Running shell command: '{command}'. RequestId: {request_id}")
        try:
            if not command:
                raise ValueError("command parameter is missing.")

            result = subprocess.run(
                command, 
                shell=True, 
                capture_output=True, 
                text=True, 
                check=True, # Raises CalledProcessError for non-zero exit codes
                timeout=timeout
            )
            return {
                "status": "success",
                "action": "run_shell_command",
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returnCode": result.returncode,
                "requestId": request_id
            }
        except subprocess.CalledProcessError as e:
            log.error(f"[System] Shell command failed for Req ID: {request_id} (Exit Code: {e.returncode}): {e}", exc_info=True)
            return {
                "status": "error",
                "action": "run_shell_command",
                "message": f"Command failed with exit code {e.returncode}",
                "stdout": e.stdout, # TimeoutExpired also has stdout/stderr
                "stderr": e.stderr,
                "returnCode": e.returncode,
                "traceback": traceback.format_exc(),
                "requestId": request_id
            }
        except subprocess.TimeoutExpired as e:
            log.error(f"[System] Shell command timed out for Req ID: {request_id} after {timeout}s: {e}", exc_info=True)
            return {
                "status": "error",
                "action": "run_shell_command",
                "message": f"Command timed out after {timeout} seconds.",
                "stdout": e.stdout, # TimeoutExpired also has stdout/stderr
                "stderr": e.stderr,
                "traceback": traceback.format_exc(),
                "requestId": request_id
            }
        except Exception as e:
            log.error(f"[System] Shell command exception for Req ID: {request_id}: {e}", exc_info=True)
            return {
                "status": "error",
                "action": "run_shell_command",
                "message": str(e) or "Unhandled exception",
                "traceback": traceback.format_exc(),
                "requestId": request_id
            }

    def launch_application(self, params):
        request_id = params.get('requestId')
        self._normalize_param_path(params, "appPath")
        app_path = params.get("appPath")
        log.info(f"[System] Launching application: {app_path}. RequestId: {request_id}")
        try:
            if not app_path:
                raise ValueError("appPath parameter is missing.")
            
            # This is platform-dependent; consider using subprocess.Popen with args
            # or a more robust library like 'applaunch' if needed.
            if os.name == 'nt':  # Windows
                os.startfile(app_path)
            elif os.uname().sysname == 'Darwin': # macOS
                subprocess.Popen(['open', app_path])
            else: # Linux/Unix
                subprocess.Popen(['xdg-open', app_path])
            
            return {
                "status": "success",
                "action": "launch_application",
                "appPath": app_path,
                "requestId": request_id
            }
        except FileNotFoundError:
            log.error(f"[System] Application not found at {app_path} for Req ID: {request_id}.")
            return {
                "status": "error",
                "action": "launch_application",
                "message": f"Application not found: {app_path}",
                "appPath": app_path,
                "requestId": request_id
            }
        except Exception as e:
            log.error(f"[System] launch_application error for Req ID: {request_id}: {e}", exc_info=True)
            return {
                "status": "error",
                "action": "launch_application",
                "message": str(e) or "Unhandled exception",
                "appPath": app_path,
                "traceback": traceback.format_exc(),
                "requestId": request_id
            }

    def activate_window(self, params):
        request_id = params.get('requestId')
        window_title = params.get("windowTitle")
        log.info(f"[System] Activating window with title: '{window_title}'. RequestId: {request_id}")
        try:
            if not window_title:
                raise ValueError("windowTitle parameter is missing.")
            
            windows = pyautogui.getWindowsWithTitle(window_title)
            if windows:
                window = windows[0]
                window.activate() # This brings the window to the foreground
                return {
                    "status": "success",
                    "action": "activate_window",
                    "windowTitle": window_title,
                    "message": f"Window '{window_title}' activated.",
                    "requestId": request_id
                }
            else:
                log.warning(f"[System] Window '{window_title}' not found for Req ID: {request_id}.")
                return {
                    "status": "error",
                    "action": "activate_window",
                    "message": f"Window '{window_title}' not found.",
                    "windowTitle": window_title,
                    "requestId": request_id
                }
        except Exception as e:
            log.error(f"[System] activate_window error for Req ID: {request_id}: {e}", exc_info=True)
            return {
                "status": "error",
                "action": "activate_window",
                "message": str(e) or "Unhandled exception",
                "traceback": traceback.format_exc(),
                "requestId": request_id
            }

    def get_file(self, params):
        # This command is expected to send the file content back to the Relay via WebSocket.
        # The Relay's consumer.py should then process the 'file_upload' message type.
        
        request_id = params.get("requestId") # Primary request ID from orchestrator
        file_path = params.get("filePath")
        
        log.info(f"[System] Processing get_file command for path: {file_path}. RequestId: {request_id}")
        log.debug(f"[System] get_file - Raw params: {params}")

        try:
            if not file_path:
                raise ValueError("filePath parameter is missing for get_file.")
            
            # Normalize path to prevent traversal issues
            self._normalize_param_path(params, "filePath")
            normalized_file_path = params["filePath"] # Use the normalized path
            
            log.debug(f"[System] get_file - Normalized file path: {normalized_file_path}")
            log.debug(f"[System] get_file - os.path.exists('{normalized_file_path}'): {os.path.exists(normalized_file_path)}")
            log.debug(f"[System] get_file - os.path.isfile('{normalized_file_path}'): {os.path.isfile(normalized_file_path)}")

            if not os.path.isfile(normalized_file_path):
                raise FileNotFoundError(f"File not found or is not a file: {normalized_file_path}")

            with open(normalized_file_path, 'rb') as f:
                encoded_content = base64.b64encode(f.read()).decode('utf-8')
            
            filename = os.path.basename(normalized_file_path)
            file_size = os.path.getsize(normalized_file_path)

            # Construct the 'file_upload' message to be put on the outgoing WebSocket queue
            message = {
                "type": "file_upload", # This type is handled by the Relay Consumer
                "file": {
                    "request_id": request_id, # Use the orchestrator's request ID for tracking
                    "filename": filename,
                    "file_content": encoded_content, # This is 'file_content'
                    "mime_type": "application/octet-stream", # Generic binary type
                    "uploaded_by_node_id": self.node_client.node_id if self.node_client else "unknown_node",
                    "file_size": file_size,
                    "original_command_type": "get_file" # Optional: add context
                }
            }
            
            if self.node_client and hasattr(self.node_client, 'outgoing_ws_queue'):
                self.node_client.outgoing_ws_queue.put(message)
                log.info(f"[System] File '{filename}' content queued for upload. RequestId: {request_id}")
                return {
                    "status": "success",
                    "action": "get_file",
                    "message": f"File '{filename}' content queued for upload.",
                    "filePath": normalized_file_path,
                    "fileName": filename,
                    "fileSize": file_size,
                    "requestId": request_id
                }
            else:
                log.error(f"[System] get_file: WebSocket queue unavailable for Req ID: {request_id}.")
                return {
                    "status": "error",
                    "action": "get_file",
                    "message": "WebSocket queue unavailable for file transfer.",
                    "requestId": request_id
                }
        except Exception as e:
            log.error(f"[System] get_file exception for Req ID: {request_id}: {e}", exc_info=True)
            return {
                "status": "error",
                "action": "get_file",
                "message": str(e) or "Unhandled exception",
                "traceback": traceback.format_exc(),
                "requestId": request_id
            }

