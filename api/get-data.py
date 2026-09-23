from http.server import BaseHTTPRequestHandler
import json
import os
from urllib.parse import parse_qs, urlparse
import requests



header = {
    "Authorization": f"Bearer {UPSTASH_REDIS_REST_TOKEN}"
}

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        

        self.send_response(200)

        parsed_url = urlparse(self.path)
        query_params = parse_qs(parsed_url.query)
        user_password = query_params.get('password', [None])[0]        

        if user_password != os.environ.get('PASSWORD'):
            self.send_response(401)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'error': 'Unauthorized'}).encode('utf-8'))
            return
        
        # 3. Write the response body (must be converted to bytes using .encode()) 📤
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        
        data = get_db_data()
        
        self.wfile.write(data.encode('utf-8'))
         
def get_db_data():
    db_data = requests.get(f"{UPSTASH_REDIS_REST_URL}/get/watchlist", headers=header)
    db_data = db_data.json().get("result") or []
    db_data = json.loads(db_data) if db_data else []
    return(db_data)
