# python-client/commands/input.py

import pyautogui
import logging

log = logging.getLogger(__name__)

class InputCommands:
    def __init__(self, node_client_ref=None):
        self.node_client_ref = node_client_ref
        # Recommended location for pyautogui global settings
        pyautogui.PAUSE = 0.05    # Add a small pause after each pyautogui call (e.g., 0.05 seconds)
        # pyautogui.FAILSAFE = True # Uncomment for debugging safety (moves mouse to 0,0 on corners for emergency stop)
        pass

    def move(self, params):
        """Moves the mouse to specified coordinates."""
        x = params.get("x")
        y = params.get("y")
        duration = params.get("duration", 0)
        log.info(f"[Input] Moving mouse to ({x},{y}) over {duration} seconds.")
        try:
            pyautogui.moveTo(x, y, duration=duration)
            return {"status": "success", "action": "mouse_move", "x": x, "y": y}
        except Exception as e:
            log.error(f"[Input] Error moving mouse to ({x},{y}): {e}", exc_info=True)
            return {"status": "error", "action": "mouse_move", "message": str(e)}

    def click(self, params):
        """
        Performs a mouse click at specified coordinates.
        Converts Java's InputEvent button mask to PyAutoGUI's string representation.
        """
        x = params.get("x")
        y = params.get("y")
        button_mask = params.get("button") # This is the integer mask from Java
        clicks = params.get("clicks", 1) 

        pyautogui_button = 'left' # Default to left click
        if button_mask == 1024: # InputEvent.BUTTON1_DOWN_MASK (Left click)
            pyautogui_button = 'left'
        elif button_mask == 2048: # InputEvent.BUTTON2_DOWN_MASK (Middle click)
            pyautogui_button = 'middle'
        elif button_mask == 4096: # InputEvent.BUTTON3_DOWN_MASK (Right click)
            pyautogui_button = 'right'
        # Add more mappings if needed for other buttons

        log.info(f"[Input] Clicking at ({x},{y}) with button: {pyautogui_button}, clicks: {clicks}")
        try:
            pyautogui.click(x=x, y=y, clicks=clicks, button=pyautogui_button) 
            return {"status": "success", "action": "mouse_click", "x": x, "y": y, "button": pyautogui_button, "clicks": clicks}
        except Exception as e:
            log.error(f"[Input] Error clicking at ({x},{y}): {e}", exc_info=True)
            return {"status": "error", "action": "mouse_click", "message": str(e)}

    def drag(self, params):
        """Drags the mouse to specified coordinates."""
        x = params.get("x")
        y = params.get("y")
        duration = params.get("duration", 0)
        button_mask = params.get("button")

        pyautogui_button = 'left'
        if button_mask == 1024: pyautogui_button = 'left'
        elif button_mask == 2048: pyautogui_button = 'middle'
        elif button_mask == 4096: pyautogui_button = 'right'

        log.info(f"[Input] Dragging mouse to ({x},{y}) with button: {pyautogui_button} over {duration} seconds.")
        try:
            pyautogui.dragTo(x, y, duration=duration, button=pyautogui_button)
            return {"status": "success", "action": "mouse_drag", "x": x, "y": y, "button": pyautogui_button}
        except Exception as e:
            log.error(f"[Input] Error dragging mouse to ({x},{y}): {e}", exc_info=True)
            return {"status": "error", "action": "mouse_drag", "message": str(e)}

    def scroll(self, params):
        """Scrolls the mouse wheel."""
        clicks = params.get("clicks")
        x = params.get("x", pyautogui.position().x) # Use current position if not specified
        y = params.get("y", pyautogui.position().y) # Use current position if not specified
        log.info(f"[Input] Scrolling mouse by {clicks} clicks at ({x},{y}).")
        try:
            pyautogui.scroll(clicks, x=x, y=y)
            return {"status": "success", "action": "mouse_scroll", "clicks": clicks}
        except Exception as e:
            log.error(f"[Input] Error scrolling mouse by {clicks} clicks: {e}", exc_info=True)
            return {"status": "error", "action": "mouse_scroll", "message": str(e)}

    def press_key(self, params):
        """Presses a single key."""
        key = params.get("key") # Can be a string like 'enter', 'shift' or character
        log.info(f"[Input] Pressing key: {key}")
        try:
            pyautogui.press(key)
            return {"status": "success", "action": "key_press", "key": key}
        except Exception as e:
            log.error(f"[Input] Error pressing key '{key}': {e}", exc_info=True)
            return {"status": "error", "action": "key_press", "message": str(e)}

    def key_combo(self, params):
        """Performs a key combination (hotkey)."""
        keys = params.get("keys") # List of strings e.g., ['ctrl', 'shift', 'esc']
        if not isinstance(keys, list) or not all(isinstance(k, str) for k in keys):
            return {"status": "error", "action": "key_combo", "message": "Keys must be a list of strings."}

        log.info(f"[Input] Pressing key combo: {keys}")
        try:
            pyautogui.hotkey(*keys)
            return {"status": "success", "action": "key_combo", "keys": keys}
        except Exception as e:
            log.error(f"[Input] Error with key combo '{keys}': {e}", exc_info=True)
            return {"status": "error", "action": "key_combo", "message": str(e)}

    def type_text(self, params):
        """Types a string of text."""
        text = params.get("text")
        log.info(f"[Input] Typing text: '{text}'")
        try:
            pyautogui.write(text)
            return {"status": "success", "action": "type_text", "typed_text": text}
        except Exception as e:
            log.error(f"[Input] Error typing text '{text}': {e}", exc_info=True)
            return {"status": "error", "action": "type_text", "message": str(e)}

    def combo_click(self, params):
        """
        Performs a key combination followed by a mouse click. Example: Ctrl+Click
        """
        keys = params.get("keys", []) # List of keys to hold down
        x = params.get("x")
        y = params.get("y")
        button_mask = params.get("button")

        pyautogui_button = 'left'
        if button_mask == 1024: pyautogui_button = 'left'
        elif button_mask == 2048: pyautogui_button = 'middle'
        elif button_mask == 4096: pyautogui_button = 'right'

        log.info(f"[Input] Executing combo_click: keys={keys}, click at ({x},{y}) with {pyautogui_button}\")")
        try:
            for key in keys:
                pyautogui.keyDown(key) # Press down all keys in combo
            pyautogui.click(x=x, y=y, button=pyautogui_button)
        finally: # Ensure keys are released even if click fails
            for key in keys:
                pyautogui.keyUp(key) # Release all keys in combo
        
        return {"status": "success", "action": "combo_click", "keys": keys, "x":x, "y":y, "button": pyautogui_button}