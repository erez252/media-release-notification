import os
import json
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)  # Handles CORS preflight headers automatically

UPSTASH_REDIS_REST_URL = os.environ.get('UPSTASH_REDIS_REST_URL')
UPSTASH_REDIS_REST_TOKEN = os.environ.get('UPSTASH_REDIS_REST_TOKEN')
TMDB_API_KEY = os.environ.get('TMDB_API_KEY')

headers = {"Authorization": f"Bearer {UPSTASH_REDIS_REST_TOKEN}"}

def is_authorized(body):
    user_password = body.get("password")
    return isinstance(user_password, str) and user_password == os.environ.get('PASSWORD')



def get_db_data():
    res = requests.get(f"{UPSTASH_REDIS_REST_URL}/get/watchlist", headers=headers)
    db_data = res.json().get("result")
    return json.loads(db_data) if db_data else []

def update_db(new_data):
    requests.post(UPSTASH_REDIS_REST_URL, headers=headers, json=["SET", "watchlist", json.dumps(new_data)])    

@app.route('/api/get-data', methods=['POST'])
def get_watchlist():
    body = request.get_json() or {}
    
    authorized = is_authorized(body)
    if not authorized:
        return jsonify({'error': 'Unauthorized'}), 401
    
    return jsonify(get_db_data()), 200

@app.route('/api', methods=['GET'])
def main_page():
    return (jsonify({'yep': 'this is the main api page there is nothing here'})), 200

@app.route('/api/remove', methods=['POST'])
def remove_item ():
    body = request.get_json() or {}
    authorized = is_authorized(body)
    if not authorized:
        return jsonify({'error': 'Unauthorized'}), 401
    movie_id = body.get("movieId")
    if movie_id and str(movie_id).isdigit():
        movie_id = int(movie_id)
    movie_type = body.get("movieType")
    if movie_type and movie_id and type(movie_id) is int:
        match = False
        db_data = get_db_data()
        for movie in db_data:
            if movie.get("type") == movie_type and movie.get("id") == movie_id:
                db_data.remove(movie)
                match = True
                break
        if not match:
            return jsonify({"error": "Unprocessable Entity", "message": "Cannot delete item because it does not exist."}), 422
        update_db(db_data)
        return jsonify({"message": f"Removed item with an id of {movie_id}"}), 200
    else:
        return jsonify({"error": "Bad Request", "message": "One or more missing required parameters"}), 400


@app.route('/api/tmdb/search', methods=['POST'])
def search_tmdb():
    body = request.get_json() or {}
    authorized = is_authorized(body)
    if not authorized:
        return jsonify({'error': 'Unauthorized'}), 401
        
    movie_name = body.get("movieName")
    
    if not (movie_name and isinstance(movie_name, str)):
        return jsonify({"error": "Bad Request", "message": "One or more missing required parameters"}), 400
    
    try:
        search_url = "https://api.themoviedb.org/3/search/multi"
        params = {
            "query": movie_name,
            "api_key": TMDB_API_KEY,
            "include_adult": "false",
            "language": "en-US",
            "page": "1",
            
        }
        search_response = requests.get(search_url, params=params)
        search_results = search_response.json()["results"]
        
        
        movie_results = []
        tv_results = []
        
        for item in search_results:
            if item.get("media_type") == "tv":
                tv_results.append(item)
            elif item.get("media_type") == "movie":
                movie_results.append(item)
        

        if not (movie_results or tv_results):
            return jsonify({"error": "No results"}), 404
        
        ordered_data = {}
        if movie_results:
            ordered_data["movie_results"] = movie_results
        if tv_results:
            ordered_data["tv_results"] = tv_results
            
        return jsonify(ordered_data), 200
        

    except KeyError:
        return jsonify({"error": "Bad Request", "message": "Something want wrong fetching tmdb data"}), 502
