from http.server import BaseHTTPRequestHandler
import os

# 🔑 Fetch the environment variable named "PASSWORD"
SECRET_PASSWORD = os.environ.get("PASSWORD")

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        # 1. Send HTTP success status (200 OK) 🟢
        self.send_response(200)
        
        # 2. Tell the browser what kind of data is coming back 📄
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        
        # 3. Write the response body (must be converted to bytes using .encode()) 📤
        self.wfile.write(SECRET_PASSWORD.encode('utf-8'))
