import os
import json
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)  # Replaces do_OPTIONS and manual Access-Control headers

UPSTASH_REDIS_REST_URL = os.environ.get('UPSTASH_REDIS_REST_URL')
UPSTASH_REDIS_REST_TOKEN = os.environ.get('UPSTASH_REDIS_REST_TOKEN')

headers = {"Authorization": f"Bearer {UPSTASH_REDIS_REST_TOKEN}"}

def get_db_data():
    res = requests.get(f"{UPSTASH_REDIS_REST_URL}/get/watchlist", headers=headers)
    db_data = res.json().get("result")
    return json.loads(db_data) if db_data else []

@app.route('/watchlist', methods=['GET'])
def get_watchlist():
    if request.args.get('password') != os.environ.get('PASSWORD'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    return jsonify(get_db_data()), 200

if __name__ == '__main__':
    app.run()
