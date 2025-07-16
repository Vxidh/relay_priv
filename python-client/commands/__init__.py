# File: commands/__init__.py

import logging
import traceback

from .input import InputCommands
from .system import SystemCommands
from .email import EmailCommands
from .api import APICallCommands
from .remote_control import RemoteControlCommands

log = logging.getLogger(__name__)

class CommandDispatcher:
    """
    Dispatches commands received from the Django Relay Server to appropriate
    handler methods on the RPA Node Client, utilizing separate command modules.
    """
    def __init__(self, node_client_ref=None):
        self.node_client_ref = node_client_ref # Store reference to NodeClient

        # Instantiate command handler classes
        # IMPORTANT: Pass node_client_ref to any command module that needs to:
        # 1. Send responses back to the server (e.g., SystemCommands for file upload status)
        # 2. Interact with NodeClient methods (e.g., send_file_to_relay)
        self.input_cmds = InputCommands(node_client_ref=self.node_client_ref) # Pass ref if input commands ever need to send responses
        self.system_cmds = SystemCommands(node_client_ref=self.node_client_ref)
        self.email_cmds = EmailCommands(node_client_ref=self.node_client_ref) # Pass ref if email commands ever need to send responses
        self.api_cmds = APICallCommands(node_client_ref=self.node_client_ref) # Pass ref if API commands ever need to send responses
        self.remote_control_cmds = RemoteControlCommands(node_client_ref=self.node_client_ref)

        # Map command types (from incoming JSON) to their specific handler methods
        # Ensure that ALL these mapped methods now expect a single 'params' dictionary as their argument.
        self.commands = {
            # Input commands (keyboard & mouse)
            'mouse_move': self.input_cmds.move,
            'mouse_click': self.input_cmds.click,
            'mouse_drag': self.input_cmds.drag,
            'mouse_scroll': self.input_cmds.scroll,
            'key_press': self.input_cmds.press_key,
            'key_combo': self.input_cmds.key_combo,
            'type_text': self.input_cmds.type_text,
            'combo_click': self.input_cmds.combo_click,

            # System commands
            'screenshot': self.system_cmds.screenshot,
            'get_screen_size': self.system_cmds.get_screen_size,
            'ping': self.system_cmds.ping,
            'open_url': self.system_cmds.open_url,
            'read_file': self.system_cmds.read_file,
            'write_file': self.system_cmds.write_file,
            'download_file': self.system_cmds.download_file, 
            'upload_file': self.system_cmds.upload_file, # This will use send_file_to_relay
            'receive_file': self.system_cmds.receive_file, 
            'run_shell_command': self.system_cmds.run_shell_command,
            'launch_application': self.system_cmds.launch_application,
            'activate_window': self.system_cmds.activate_window,
            'wait': self.system_cmds.wait,
            'get_file': self.system_cmds.get_file, 

            # Email commands
            'send_email': self.email_cmds.send_email,
            'read_latest_email': self.email_cmds.read_latest_email,

            # Local API Call Commands
            'get_data_from_local_api': self.api_cmds.get_data_from_local_api,
            'post_data_to_local_api': self.api_cmds.post_data_to_local_api, 

            # Remote control commands
            'start_remote_control': self.remote_control_cmds.start_remote_control,
            'stop_remote_control': self.remote_control_cmds.stop_remote_control,
            'send_input': self.remote_control_cmds.send_input,
        }

    def execute_command(self, command_data):
        """
        Executes a given command based on its 'commandType'.
        Returns a dictionary containing the result status and any response data.
        This method is designed to return a unified response format for NodeClient.
        """
        command_type = command_data.get('commandType')
        request_id = command_data.get('requestId')
        
        # Extract parameters using the 'params' key as sent by Java Batch Server
        params = command_data.get('params', {}) 
        
        # Ensure requestId is available within params for handlers that need it
        # This allows handlers to return requestId in their internal results
        params['requestId'] = request_id 

        if not command_type:
            log.error(f"Missing 'commandType' field in command_data: {command_data}")
            return {
                "status": "error",
                "message": "Missing 'commandType' field",
                "requestId": request_id
            }

        if command_type not in self.commands:
            log.error(f"Unknown command: {command_type}. Full command_data: {command_data}")
            return {
                "status": "error",
                "message": f"Unknown command: {command_type}",
                "requestId": request_id
            }

        try:
            log.info(f"[Dispatcher] Processing command: {command_type} (Req ID: {request_id})")
            # Call the appropriate handler method from the mapped dictionary, passing the 'params' dict
            result = self.commands[command_type](params) # Pass the combined params dict

            # Ensure the result from the command handler includes the requestId
            if isinstance(result, dict):
                if 'requestId' not in result:
                    result['requestId'] = request_id
                
                return {
                    "status": result.get('status', 'success'), 
                    "message": result.get('message', f"Command '{command_type}' executed."),
                    "response": result, # Full result from the command handler
                    "requestId": request_id 
                }
            else:
                log.error(f"[Dispatcher] Command handler for '{command_type}' returned unexpected type: {type(result)} (expected dict). Result: {result}")
                return {
                    "status": "error",
                    "message": f"Command handler returned invalid type for '{command_type}'.",
                    "requestId": request_id,
                    "response": str(result)
                }

        except Exception as e:
            log.error(f"Error processing command {command_type} (Req ID: {request_id}): {e}", exc_info=True)
            return {
                "status": "error",
                "message": f"Exception during command execution: {str(e)}",
                "traceback": traceback.format_exc(),
                "requestId": request_id
            }