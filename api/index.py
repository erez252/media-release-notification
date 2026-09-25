import os
import json
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from datetime import datetime, timezone

app = Flask(__name__)
CORS(app)  # Handles CORS preflight headers automatically

UPSTASH_REDIS_REST_URL = os.environ.get('UPSTASH_REDIS_REST_URL')
UPSTASH_REDIS_REST_TOKEN = os.environ.get('UPSTASH_REDIS_REST_TOKEN')
TMDB_API_KEY = os.environ.get('TMDB_API_KEY')
DISCORD_URL = os.environ.get('DISCORD_URL')

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
            if movie.get("media_type") == movie_type and movie.get("id") == movie_id:
                db_data.remove(movie)
                match = True
                break
        if not match:
            return jsonify({"error": "Unprocessable Entity", "message": "Cannot delete item because it does not exist."}), 422
        update_db(db_data)
        return jsonify({"message": f"Removed item with an id of {movie_id}"}), 200
    else:
        return jsonify({"error": "Bad Request", "message": "One or more missing required parameters"}), 400


@app.route('/api/add', methods=['POST'])
def add_item():
    
    try:
        body = request.get_json() or {}

        authorized = is_authorized(body)
        if not authorized:
            return jsonify({'error': 'Unauthorized'}), 401

        media_id = body.get("mediaId")
        media_type = body.get("mediaType")
        if media_id and str(media_id).isdigit():
            media_id = int(media_id)
        if not media_id or not str(media_id).isdigit() or not (media_type == "tv" or media_type == "movie"):
            return jsonify({"error": "Bad Request", "message": "One or more missing required parameters"}), 400


        db_data = get_db_data()
        for item in db_data:
            if item.get("media_type") == media_type and item.get("id") == media_id:
                return jsonify({"error": "Unprocessable Entity", "message": "Cannot add item because it is already exists."}), 422


        movie_response = requests.get(f"https://api.themoviedb.org/3/{media_type}/{media_id}?api_key={TMDB_API_KEY}")
        if movie_response.status_code == 404:
            return jsonify({"error": "No results"}), 404

        justwatch_data_url = f"https://api.themoviedb.org/3/{media_type}/{media_id}/watch/providers?api_key={TMDB_API_KEY}"
        response = requests.get(justwatch_data_url)
        digital = False
        watch_data = {}
        if response.status_code == 200:
                watch_data = response.json()
        if watch_data.get("results", []):
            digital = True
            
            
        
        movie_data = movie_response.json()

        raw_movie_data = movie_response.json()
        
        movie_data = {
                "id": movie_data.get("id"),
                "title": movie_data.get("title") or movie_data.get("name"),
                "poster_path": movie_data.get("poster_path"),
                "overview": movie_data.get("overview"),
                "runtime": movie_data.get("runtime"),
                "status": movie_data.get("status"),
                "genres": movie_data.get("genres"),
                "media_type": "movie" if movie_data.get("title") else "tv",
                "last_notification": None,
                "digital": digital,
                "imdb_id": None,
                "tvdb_id": None
            }
        if media_type == "movie":
            movie_data["release_date"] = raw_movie_data.get("release_date", None)
            movie_data["runtime"] = raw_movie_data.get("runtime", None)
        else:
            movie_data["first_air_date"] = raw_movie_data.get("first_air_date", None)
            movie_data["last_air_date"] = raw_movie_data.get("last_air_date", None)
            
            last_episode_to_air = raw_movie_data.get("last_episode_to_air", {})
            if last_episode_to_air:
                movie_data["last_episode_to_air"] = last_episode_to_air.get("air_date", None)
            else:
                movie_data["last_episode_to_air"] = None

            response = requests.get(f"https://api.themoviedb.org/3/tv/{raw_movie_data.get('id')}/external_ids?api_key={TMDB_API_KEY}")

            external_ids = response.json()
            
            if external_ids.get("imdb_id"):
                movie_data["imdb_id"] = external_ids.get("imdb_id")
            if external_ids.get("tvdb_id"):
                movie_data["tvdb_id"] = external_ids.get("tvdb_id")
                
            now_iso = datetime.now(timezone.utc).isoformat()
            movie_data["last_notification"] = now_iso
              
        
        db_data.append(movie_data)
        response = requests.post(UPSTASH_REDIS_REST_URL, headers=headers, json=["SET", "watchlist", json.dumps(db_data)])
        if response.status_code == 200:
            return jsonify({"success": "true", "message": "Added the media"}), 200

        return jsonify({"error": "something went wrong", "message": "something went wrong while adding the media"}), 500
    except (TypeError, requests.exceptions.RequestException):
        return jsonify({"error": "something went wrong", "message": "something went wrong while adding the media"}), 500
    
 

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
        return jsonify({"error": "Bad Request", "message": "something went wrong fetching tmdb data"}), 502


@app.route('/api/checker/movie', methods=['POST'])
def check_movie():
    try:

        auth_header = request.headers.get("authorization", "")
        if not auth_header == f"Bearer {os.environ.get('PASSWORD')}":
            return jsonify({'error': 'Unauthorized'}), 401
        
        db_data = get_db_data()
        needs_update = []
        for item in db_data:
                justwatch_data = {}
                if item.get("media_type") == "movie" and not item.get("digital"):

                    response = requests.get(f"https://api.themoviedb.org/3/{item.get('media_type')}/{item.get('id')}/watch/providers?api_key={TMDB_API_KEY}", timeout=5)
                    if response.status_code == 200:
                        justwatch_data = response.json()
                    elif response.status_code == 429:
                        break

                    if justwatch_data.get("results", []):
                        item["digital"] = True
                        needs_update.append({"title": item.get('title')})
        if needs_update:
            requests.post(UPSTASH_REDIS_REST_URL, headers=headers, json=["SET", "watchlist", json.dumps(db_data)])
            for movie in needs_update:
                requests.post(DISCORD_URL, json={"content": f"{movie.get('title')} is now available to watch"})

        return jsonify({"success": "true", "message": "check_movie checked successfully"}), 200
    except Exception as e:
        return jsonify({"error": "Bad Gateway", "message": f"Server error: {e}"}), 502
        
