import websocket

ws_url = "ws://localhost:8000/ws/rpa-node/9b5e88d9-252c-4a00-8b0d-9f1e150f562d/?token=iATk0QJPNb4VjiB1FY0WuQdnA9jlc2"
try:
    ws = websocket.create_connection(ws_url)
    print("Connected!")
    print(ws.recv())
    ws.close()
except Exception as e:
    print("WebSocket connection failed:", e)