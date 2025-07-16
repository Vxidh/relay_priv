# File: commands/remote_control.py

import threading
import time

class RemoteControlCommands:
    def __init__(self, node_client_ref=None):
        self.node_client_ref = node_client_ref
        self.active_controller = None  # Track which controller is active
        self.streaming = False
        self.stream_thread = None

    def start_remote_control(self, params):
        controller_id = params.get('controllerId')
        node_id = params.get('nodeId')
        request_id = params.get('requestId')
        if self.active_controller:
            return {
                'status': 'error',
                'message': f'Node {node_id} is already being controlled by {self.active_controller}',
                'requestId': request_id
            }
        self.active_controller = controller_id
        self.streaming = True
        # Start streaming thread (dummy for now)
        self.stream_thread = threading.Thread(target=self._stream_images, args=(node_id, controller_id), daemon=True)
        self.stream_thread.start()
        return {
            'status': 'success',
            'message': f'Remote control started for node {node_id} by {controller_id}',
            'requestId': request_id
        }

    def stop_remote_control(self, params):
        controller_id = params.get('controllerId')
        node_id = params.get('nodeId')
        request_id = params.get('requestId')
        if self.active_controller != controller_id:
            return {
                'status': 'error',
                'message': 'You are not the active controller.',
                'requestId': request_id
            }
        self.streaming = False
        self.active_controller = None
        return {
            'status': 'success',
            'message': f'Remote control stopped for node {node_id}',
            'requestId': request_id
        }

    def _stream_images(self, node_id, controller_id):
        import io
        try:
            import pyautogui
        except ImportError:
            print("pyautogui is required for screenshot capture.")
            return
        frame_interval = 0.1  # 10 frames per second
        while self.streaming:
            # Capture screenshot
            screenshot = pyautogui.screenshot()
            buf = io.BytesIO()
            screenshot.save(buf, format='JPEG')
            img_bytes = buf.getvalue()
            # Send image bytes via node_client_ref (must implement send_image_frame)
            if self.node_client_ref and hasattr(self.node_client_ref, 'send_image_frame'):
                try:
                    self.node_client_ref.send_image_frame(img_bytes)
                except Exception as e:
                    print(f"Error sending image frame: {e}")
            time.sleep(frame_interval)

    def send_input(self, params):
        controller_id = params.get('controllerId')
        node_id = params.get('nodeId')
        input_data = params.get('inputData')
        request_id = params.get('requestId')
        if self.active_controller != controller_id:
            return {
                'status': 'error',
                'message': 'You are not the active controller.',
                'requestId': request_id
            }
        # Here you would process the input_data (mouse/keyboard events)
        return {
            'status': 'success',
            'message': f'Input processed for node {node_id}',
            'requestId': request_id
        }
