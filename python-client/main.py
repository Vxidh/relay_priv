# File: main.py
import websocket # pip install websocket-client
import threading
import time
import json
import uuid
import os
import queue
import base64
import logging
import requests # pip install requests
import webbrowser
import hashlib
import secrets
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import platform
import shutil

# Import the NodeClient from the local file
from NodeClient import NodeClient # Assuming NodeClient.py is in the same directory
# Set up logging for the RPA Client
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger('RPAClient')
DJANGO_RELAY_SERVER_BASE_URL = "http://localhost:8000/api/" # Base for HTTP APIs (Note: This is still here for OAuth, but not for node verification)
DJANGO_RELAY_SERVER_WS_URL = "ws://localhost:8000/ws/rpa-node/"
NODE_ID_FILE = "rpa_client_node_id.txt"
ACCESS_TOKEN_FILE = "rpa_client_access_token.txt"
REFRESH_TOKEN_FILE = "rpa_client_refresh_token.txt"
TOKEN_EXPIRY_FILE = "rpa_client_token_expiry.txt"
RPA_CLIENT_DOWNLOAD_DIR = "rpa_client_downloads"
# Ensure this directory exists on the RPA client machine
os.makedirs(RPA_CLIENT_DOWNLOAD_DIR, exist_ok=True)
logger.info(f"RPA Client will save received files to: {os.path.abspath(RPA_CLIENT_DOWNLOAD_DIR)}")

# Global variables for tokens and Node ID
NODE_ID = None
ACCESS_TOKEN = None
REFRESH_TOKEN = None
TOKEN_EXPIRY = None # Unix timestamp when access token expires
NODE_CLIENT_INSTANCE = None # Global NodeClient instance

# --- Helper Functions ---

def get_or_create_node_id():
    """
    Prompt user for 6-character alphanumeric Node ID.
    Use Tkinter GUI if possible, otherwise fallback to CLI.
    Saves and loads Node ID from file.
    """
    global NODE_ID
    if os.path.exists(NODE_ID_FILE):
        with open(NODE_ID_FILE, "r") as f:
            NODE_ID = f.read().strip()
        logger.info(f"Loaded existing Node ID from file: {NODE_ID}")
        return True

    try:
        import tkinter as tk
        from tkinter import simpledialog, messagebox

        root = tk.Tk()
        root.withdraw()  # Hide main window

        while True:
            node_id_input = simpledialog.askstring("Node ID Required", "Enter your 6-character alphanumeric node ID:", parent=root)
            if node_id_input is None:
                if messagebox.askyesno("Exit?", "No node ID entered. Exit RPA Client?"):
                    root.destroy()
                    exit(0)
                else:
                    continue  # Re-prompt
            node_id_input = node_id_input.strip()
            if len(node_id_input) == 6 and node_id_input.isalnum():
                NODE_ID = node_id_input
                with open(NODE_ID_FILE, "w") as f:
                    f.write(NODE_ID)
                logger.info(f"Using centrally-issued Node ID (from Tkinter input): {NODE_ID}")
                root.destroy()
                return True
            else:
                messagebox.showerror("Invalid Node ID", "Please enter a valid 6-character alphanumeric node ID.")
    except ImportError:
        logger.warning("Tkinter not available, falling back to CLI input for Node ID.")
    except Exception as e:
        logger.error(f"Error in Tkinter Node ID input: {e}, falling back to CLI input.")

    # CLI fallback
    while True:
        user_input = input("Enter your 6-character alphanumeric node ID: ").strip()
        if len(user_input) == 6 and user_input.isalnum():
            NODE_ID = user_input
            with open(NODE_ID_FILE, "w") as f:
                f.write(NODE_ID)
            logger.info(f"Using centrally-issued Node ID (from CLI input): {NODE_ID}")
            return True
        else:
            print("Invalid node ID. Please enter a valid 6-character alphanumeric value.")

# Removed the verify_node_id_with_relay function as it's no longer needed
# def verify_node_id_with_relay(node_id, access_token):
#     ... (function content removed) ...

def save_tokens(access_token, refresh_token, expires_in):
    """Saves access and refresh tokens to local files."""
    global ACCESS_TOKEN, REFRESH_TOKEN, TOKEN_EXPIRY
    ACCESS_TOKEN = access_token
    REFRESH_TOKEN = refresh_token
    # Store expiry time, 60s buffer to refresh before actual expiry
    TOKEN_EXPIRY = time.time() + expires_in - 60
    with open(ACCESS_TOKEN_FILE, "w") as f:
        f.write(ACCESS_TOKEN)
    with open(REFRESH_TOKEN_FILE, "w") as f:
        f.write(REFRESH_TOKEN)
    with open(TOKEN_EXPIRY_FILE, "w") as f:
        f.write(str(TOKEN_EXPIRY))
    logger.info("Access and Refresh tokens saved.")

def load_tokens():
    """Loads access and refresh tokens from local files."""
    global ACCESS_TOKEN, REFRESH_TOKEN, TOKEN_EXPIRY
    if (os.path.exists(ACCESS_TOKEN_FILE) and
        os.path.exists(REFRESH_TOKEN_FILE) and
        os.path.exists(TOKEN_EXPIRY_FILE)):
        try:
            with open(ACCESS_TOKEN_FILE, "r") as f:
                ACCESS_TOKEN = f.read().strip()
            with open(REFRESH_TOKEN_FILE, "r") as f:
                REFRESH_TOKEN = f.read().strip()
            with open(TOKEN_EXPIRY_FILE, "r") as f:
                TOKEN_EXPIRY = float(f.read().strip())
            logger.info("Loaded existing access/refresh tokens.")
            return True
        except Exception as e:
            logger.error(f"Error loading tokens: {e}. Tokens might be corrupted. Deleting them.")
            clear_tokens() # Clear corrupted tokens
            return False
    logger.info("No existing access/refresh tokens found.")
    return False

def clear_tokens():
    """Deletes all token files."""
    for f in [ACCESS_TOKEN_FILE, REFRESH_TOKEN_FILE, TOKEN_EXPIRY_FILE]:
        try:
            if os.path.exists(f):
                os.remove(f)
                logger.info(f"Deleted {f}")
        except Exception as e:
            logger.warning(f"Could not delete {f}: {e}")

def is_token_expired():
    """Checks if the loaded access token is expired."""
    return TOKEN_EXPIRY is None or time.time() >= TOKEN_EXPIRY

# --- PKCE Helper Functions ---
def generate_code_verifier():
    """Generates a high-entropy cryptographically random string for PKCE."""
    return secrets.token_urlsafe(64)

def generate_code_challenge(verifier):
    """Generates the S256 code challenge from the code verifier."""
    digest = hashlib.sha256(verifier.encode('ascii')).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b'=').decode('ascii')

# --- PKCE OAuth2 Flow ---
OAUTH2_CLIENT_ID = "bc0xM6l96NYdvXghcapdtkP7hiSKHSeCFAH5E9T3"  # Set this to your DOT Application's client_id
OAUTH2_AUTH_URL = "http://localhost:8000/o/authorize/"
OAUTH2_TOKEN_URL = "http://localhost:8000/o/token/"
OAUTH2_REDIRECT_URI = "http://localhost:8080/callback"
OAUTH2_SCOPES = "rpa:connect rpa:commands" # Ensure these scopes match your Django OAuth2 Provider setup

class OAuth2CallbackHandler(BaseHTTPRequestHandler):
    """
    A simple HTTP server handler to capture the authorization code from the OAuth2 redirect.
    """
    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        if 'code' in params:
            self.server.auth_code = params['code'][0]
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Authentication successful. You can close this window.")
        else:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Missing code in callback.")
        # Ensure the server stops after receiving the code
        threading.Thread(target=self.server.shutdown).start()


def get_or_create_access_tokens():
    """
    Manages loading, refreshing, or performing a new PKCE authorization flow
    to obtain access tokens.
    """
    global ACCESS_TOKEN, REFRESH_TOKEN
    if load_tokens():
        if not is_token_expired():
            logger.info("Using existing valid access token.")
            return True
        else:
            logger.info("Access token expired. Attempting to refresh.")
            if refresh_access_token():
                return True
            else:
                logger.warning("Failed to refresh token. Will try PKCE authorization.")
    logger.info("No valid tokens found or refresh failed. Initiating PKCE OAuth2 flow.")
    return pkce_authorization_flow()

def refresh_access_token():
    """Attempts to refresh the access token using the refresh token."""
    global ACCESS_TOKEN, REFRESH_TOKEN, TOKEN_EXPIRY
    if not REFRESH_TOKEN:
        logger.warning("No refresh token available. Cannot refresh access token.")
        return False
    logger.info("Attempting to refresh access token...")
    data = {
        'grant_type': 'refresh_token',
        'refresh_token': REFRESH_TOKEN,
        'client_id': OAUTH2_CLIENT_ID,
    }
    try:
        response = requests.post(OAUTH2_TOKEN_URL, data=data)
        response.raise_for_status() # Raise an exception for HTTP errors
        token_data = response.json()
        save_tokens(token_data["access_token"], token_data["refresh_token"], token_data["expires_in"])
        logger.info("Access token refreshed successfully.")
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to refresh access token: {e}. Response: {response.text if 'response' in locals() else 'N/A'}")
        clear_tokens() # Invalidate tokens if refresh fails
        return False
    except Exception as e:
        logger.error(f"An unexpected error occurred during token refresh: {e}")
        clear_tokens()
        return False

def pkce_authorization_flow():
    """Performs the PKCE OAuth2 authorization code flow."""
    code_verifier = generate_code_verifier()
    code_challenge = generate_code_challenge(code_verifier)
    state = secrets.token_urlsafe(16) # For CSRF protection

    auth_url = (
        f"{OAUTH2_AUTH_URL}?response_type=code&client_id={OAUTH2_CLIENT_ID}"
        f"&redirect_uri={OAUTH2_REDIRECT_URI}"
        f"&scope={OAUTH2_SCOPES}"
        f"&state={state}"
        f"&code_challenge={code_challenge}"
        f"&code_challenge_method=S256"
    )
    print(f"\nOpening browser for authentication: {auth_url}")
    webbrowser.open(auth_url)

    # Start a local HTTP server in a separate thread to listen for the redirect
    server = HTTPServer(('localhost', 8080), OAuth2CallbackHandler)
    server.auth_code = None
    server_thread = threading.Thread(target=server.serve_forever)
    server_thread.daemon = True # Allow the main program to exit even if this thread is running
    server_thread.start()

    logger.info("Waiting for OAuth2 redirect with code...")
    # Wait for the auth_code to be set by the handler (with a timeout)
    timeout_start = time.time()
    while server.auth_code is None and (time.time() - timeout_start < 60): # 60 seconds timeout
        time.sleep(0.5)
    
    if server.auth_code is None:
        logger.error("Timed out waiting for authorization code from browser.")
        server.shutdown()
        return False
    
    logger.info("Received authorization code. Shutting down local server.")
    server.shutdown()
    data = {
        'grant_type': 'authorization_code',
        'code': server.auth_code,
        'redirect_uri': OAUTH2_REDIRECT_URI,
        'client_id': OAUTH2_CLIENT_ID,
        'code_verifier': code_verifier,
    }
    try:
        response = requests.post(OAUTH2_TOKEN_URL, data=data)
        response.raise_for_status()
        token_data = response.json()
        save_tokens(token_data["access_token"], token_data["refresh_token"], token_data["expires_in"])
        logger.info("PKCE OAuth2 flow successful. Tokens saved.")
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to exchange code for tokens: {e}. Response: {response.text if 'response' in locals() else 'N/A'}")
        clear_tokens()
        return False
    except Exception as e:
        logger.error(f"An unexpected error occurred during token exchange: {e}")
        clear_tokens()
        return False

def detect_installed_browsers():
    """Detects common installed browsers on the system."""
    browsers = {
        "chrome": [
            "chrome",  # Linux
            r"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",  # Windows
            r"C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe"
        ],
        "firefox": [
            "firefox",  # Linux
            r"C:\\Program Files\\Mozilla Firefox\\firefox.exe",  # Windows
            r"C:\\Program Files (x86)\\Mozilla Firefox\\firefox.exe"
        ],
        "edge": [
            "microsoft-edge",  # Linux (Edge for Linux)
            r"C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",  # Windows
            r"C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe"
        ]
    }
    available = []
    for browser, paths in browsers.items():
        for path in paths:
            if shutil.which(path) or os.path.exists(path):
                available.append(browser)
                break
    return available

# --- Main RPA Client Logic ---

def main():
    global NODE_CLIENT_INSTANCE, NODE_ID, ACCESS_TOKEN
    clear_tokens()

    # 1. Authenticate and get tokens
    if not get_or_create_access_tokens():
        logger.error("RPA Client could not authenticate. Exiting.")
        return

    logger.info("RPA Client authenticated successfully.")

    # 2. Get/Create Node ID
    # The uniqueness check is now handled by the WebSocket connection itself.
    # If the Node ID is not unique, the WebSocket connection will be closed
    # by the server with a specific close code (e.g., 4409), which NodeClient
    # handles in its on_close method.
    if not get_or_create_node_id():
        logger.info("User cancelled Node ID input. Exiting.")
        return

    initial_node_metadata = {
        "os": platform.system(),
        "os_version": platform.version(),
        "python_version": platform.python_version(),
        "hostname": platform.node(),
        "browser_compatibility": detect_installed_browsers(),
        "extra": {}
    }

    # IMPORTANT: The server_url passed to NodeClient should be the full WebSocket URL
    # for the specific node, e.g., "ws://localhost:8000/ws/rpa-node/<NODE_ID>/".
    NODE_CLIENT_INSTANCE = NodeClient(
        server_url=f"{DJANGO_RELAY_SERVER_WS_URL}{NODE_ID}/", # Full WebSocket URL with node_id
        node_id=NODE_ID,
        access_token=ACCESS_TOKEN,
        download_dir=RPA_CLIENT_DOWNLOAD_DIR, # Pass download directory
        initial_metadata=initial_node_metadata # Pass initial metadata
    )

    # Start the WebSocket connection in a background thread
    # The connect() method of NodeClient is blocking (run_forever)
    # so it must be run in a separate thread.
    wst = threading.Thread(target=NODE_CLIENT_INSTANCE.connect, daemon=True)
    wst.start()

    # Wait up to 10 seconds for the WebSocket connection to establish
    for _ in range(20): # 20 * 0.5 seconds = 10 seconds
        if NODE_CLIENT_INSTANCE.is_connected():
            break
        time.sleep(0.5)

    if NODE_CLIENT_INSTANCE.is_connected():
        logger.info("WebSocket connected. RPA Client is running.")
        try:
            # Keep the main thread alive. This is where you might add a UI loop
            # or simply wait for a shutdown signal.
            while True:
                # This loop can be used for periodic tasks if needed,
                # otherwise just keep the main thread alive.
                time.sleep(1) # Sleep to prevent busy-waiting
        except KeyboardInterrupt:
            logger.info("RPA Client stopped by user (Ctrl+C).")
        finally:
            if NODE_CLIENT_INSTANCE:
                NODE_CLIENT_INSTANCE.stop() # Gracefully close WebSocket and threads
                logger.info("WebSocket closed and NodeClient threads stopped.")
    else:
        logger.error("Failed to connect WebSocket after waiting. RPA Client will exit.")

if __name__ == "__main__":
    main()