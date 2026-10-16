from math import e
import os
import time
import json
import requests
from flask import Flask, request, jsonify, Response
from flask_cors import CORS
from datetime import date, datetime, timezone, timedelta
import threading
from iso3166 import countries
app = Flask(__name__)
CORS(app)  # Handles CORS preflight headers automatically
import urllib.parse


UPSTASH_REDIS_REST_URL = os.environ.get('UPSTASH_REDIS_REST_URL')
UPSTASH_REDIS_REST_TOKEN = os.environ.get('UPSTASH_REDIS_REST_TOKEN')
TMDB_API_KEY = os.environ.get('TMDB_API_KEY')
DISCORD_URL = os.environ.get('DISCORD_URL')
QSTASH_TOKEN = os.environ.get('QSTASH_TOKEN')
QSTASH_URL = os.environ.get('QSTASH_URL')
IGDB_CLIENT_ID = os.environ.get('IGDB_CLIENT_ID')
IGDB_ACCESS_TOKEN = os.environ.get('IGDB_ACCESS_TOKEN')
STREMIO_AUTHKEY = os.environ.get('STREMIO_AUTHKEY')
NTFY_SUB_CHANNEL = os.environ.get('NTFY_SUB_CHANNEL')

headers = {"Authorization": f"Bearer {UPSTASH_REDIS_REST_TOKEN}"}
qstash_header= {"Authorization": f"Bearer {QSTASH_TOKEN}"}
igdb_headers = {
  "Content-Type": "application/json",
  'Client-ID': IGDB_CLIENT_ID,
  'Authorization': f"Bearer {IGDB_ACCESS_TOKEN}"
}
stremio_headers = {
    "Content-Type": "application/json"
}

def is_authorized(body):
    user_password = body.get("password")
    return isinstance(user_password, str) and user_password == os.environ.get('PASSWORD')

def get_db_data_v2():
    response = requests.post(
    UPSTASH_REDIS_REST_URL,
    headers=headers,
    json=["HVALS", "Watchlist-V2"]
    )

    raw_list = response.json()["result"]

    watchlist = [json.loads(item) for item in raw_list if item.startswith('{')]
    
    return watchlist

def get_item_data_from_db(item):
    field = f"{item.get('media_type', "")}:{item.get('id', "")}"
    response = requests.post(
        UPSTASH_REDIS_REST_URL,
        headers=headers,
        json=["HGET", "Watchlist-V2", field]
    )
    data = response.json().get('result', [])
    if data:
        data = json.loads(data)
    
    return(data or {})   

def update_one_item_in_db(item):
    field = f"{item.get('media_type')}:{item.get('id')}"
    requests.post(
      UPSTASH_REDIS_REST_URL,
      headers=headers,
      json=["HSET", "Watchlist-V2", field, json.dumps(item)]
    )
    
def update_db(new_data):
    # requests.post(UPSTASH_REDIS_REST_URL, headers=headers, json=["SET", "watchlist", json.dumps(new_data)])
    payload = ["HSET", "Watchlist-V2"]
    for item in new_data:
        media_type = item.get("media_type")
        item_id = item.get("id")
        field_name = f"{media_type}:{item_id}"
        json_value = json.dumps(item)
        payload.append(field_name)
        payload.append(json_value)
        
    requests.post(
        UPSTASH_REDIS_REST_URL,
        headers=headers,
        json=payload
    )

def check_if_digital(id):
    response = requests.get(f"https://api.themoviedb.org/3/movie/{id}/release_dates?api_key={TMDB_API_KEY}")
    data = response.json()
    now = datetime.now(timezone.utc)
    results = data.get('results' , [])
    if not results:
        return False
    for country in results:
        if country.get('release_dates', []):
            for dates in country['release_dates']:
                if dates['type'] >= 4:
                    result_date = datetime.fromisoformat(dates['release_date'])
                    seconds = int(result_date.timestamp())
                    if seconds - now.timestamp() <= 0:
                        return True
                    
    return False

def send_movie_notification(item, time):
    

            
    genres = []
    for genre in item.get('genres', []):
        genres.append(genre["name"])
    
    discord_msg = {
          "content": "🎥 **New Movie Digital Release!**",
          "embeds": [
            {
              "title": item.get('title'),
              "description": f"Now available to stream.",
              "color": 10038562,
              "fields": [
                {
                  "name": "Release Date",
                  "value": f"`{item.get('release_date')}`",
                  "inline": True
                },
                {
                  "name": "Runtime",
                  "value": f"`{item.get('runtime')}`",
                  "inline": True
                },
                {
                  "name": "Genres",
                  "value": f"{', '.join(genres)}",
                  "inline": False
                }
              ],
              "image": {
                "url": f"https://image.tmdb.org/t/p/w780{item.get("poster_path")}"
              },
              "footer": {
                "text": "Movie Release Notification"
              },
              "timestamp": time
            }
          ]
        }
    if item.get("notifications"):
        requests.post(DISCORD_URL, json=discord_msg)

def send_game_to_qstush(delay, body):
    target_url = "https://media-release-notification.vercel.app/api/notification/game"
    qstash_task_header= {
        "Authorization": f"Bearer {QSTASH_TOKEN}",
        "Content-Type": "application/json",
        "Upstash-Delay": f"{delay}s",
        "Upstash-Forward-Authorization": f"Bearer {os.environ.get('PASSWORD')}"
    }
    qstash_publish_endpoint = f"{QSTASH_URL}/publish/{target_url}"
    qstash_task_payload = body
    
    requests.post(qstash_publish_endpoint, headers=qstash_task_header, json=qstash_task_payload)

def get_game_results(query):
    
    headers = {
        "Content-Type": "application/json",
        'Client-ID': IGDB_CLIENT_ID,
        'Authorization': f"Bearer {IGDB_ACCESS_TOKEN}"
    }
    
    fields = "name,cover.image_id,first_release_date,game_type,game_status.status,genres.name,hypes,summary,first_release_date,rating,rating_count"
    filters = "themes != (42) & game_type = (0, 8)"
    
    response = requests.post(f"https://api.igdb.com/v4/games" ,headers=headers, data=f'fields {fields}; where {filters}; search "{query}";')
    if response.status_code != 200:
        return []
    
    games = response.json()
    custom_data = []
    for game in games:
        
        timestamp_raw = game.get("first_release_date")
        release_date = ""
        if timestamp_raw is not None:
            original_release_date = float(timestamp_raw)
            release_date = datetime.fromtimestamp(original_release_date, timezone.utc).date().isoformat()
            
        cover = game.get("cover")
        poster_path = cover.get("image_id", "") if cover else ""
        
        custom_data.append(
            {
                "adult": False,
                'id': game.get("id", ""),
                "title": game.get("name", ""),
                "overview": game.get("summary", ""),
                "poster_path": poster_path,
                "media_type": "game",
                "genres": game.get("genres", []),
                'popularity': game.get("hype", 0),
                "release_date": release_date,
                "softcore": False,
                "video": False,
                "vote_average": game.get("rating", 0),
                "vote_count": game.get("rating_count", 0),
            }
        )    
    
    return custom_data    
    
def get_game_by_id(id):
    
    headers = {
        "Content-Type": "application/json",
        'Client-ID': IGDB_CLIENT_ID,
        'Authorization': f"Bearer {IGDB_ACCESS_TOKEN}"
    }
    
    fields = "name,cover.image_id,first_release_date,game_type,game_status,genres.name,hypes,summary,first_release_date,rating,rating_count"
    
    response = requests.post(f"https://api.igdb.com/v4/games" ,headers=headers, data=f'fields {fields}; where id = {id};')
    
    if not response.json():
        return False
    
    game = response.json()[0]
    
    # hendle time and if digital
    timestamp_raw = game.get("first_release_date")
    release_date = ""
    digital = False
    if timestamp_raw is not None:
        original_release_date = float(timestamp_raw)
        release_date = datetime.fromtimestamp(original_release_date, timezone.utc).date().isoformat()
        
        if datetime.fromtimestamp(original_release_date, timezone.utc) <= datetime.now(timezone.utc):
            digital = True

    status = "Upcoming"
    released = False
    if digital:
        status = "Released"
        released = True
    
    cover = game.get("cover")
    poster_path = cover.get("image_id", "") if cover else ""
    
    vote_average = game.get("rating", 0)
        
    custom_data = {
            'id': game.get("id", ""),
            "title": game.get("name", ""),
            "poster_path": poster_path,
            "overview": game.get("summary", ""),
            "runtime": "",
            "status": status,
            "genres": game.get("genres", []),
            "media_type": "game",
            "last_notification": None,
            "digital": digital,
            "release_date": release_date,
            'popularity': game.get("hypes", 0),
            "vote_average": vote_average,
            "vote_count": game.get("rating_count", 0),
            "added_date": datetime.now(timezone.utc).isoformat(),
            "released": released,
            "notifications": True,
            "notifications_enabled_at": datetime.now(timezone.utc).isoformat(),
            "notified_content_ids": []
        }
    return(custom_data)

def check_if_item_in_the_list(media_id, media_type):
    db_data = get_db_data_v2()
    for item in db_data:
        if item.get("media_type") == media_type and item.get("id") == media_id:
            return True
    return False

def send_game_notification(body):
    try:
        db_data = get_db_data_v2()
        db_item = next((item for item in db_data if item.get("id") == body.get("id")), {})

        if body.get("game_type_id") == 0:
            if db_item:
                db_item["released"] == True
                update_one_item_in_db(db_item)
            discord_msg = {
                "content": "🎮 **New Game Released!**",
                "embeds": [
                  {
                    "title": body.get("title"),
                    "description": "Now available to play.",
                    "color": 15418782,
                    "fields": [
                      {
                        "name": "Release Date",
                        "value": f"`{body.get("release_date")}`",
                        "inline": True
                      },
                      {
                        "name": "Developer",
                        "value": body.get("developer") or "Unknown(?)",
                        "inline": True
                      },
                      {
                        "name": "Platforms",
                        "value": ", ".join(body.get("platforms") or [])
                      },
                      {
                        "name": "Genres",
                        "value": ", ".join(body.get("genres") or [])
                      }
                    ],
                    "footer": {
                      "text": "Game Release Notification"
                    },
                    "timestamp": body.get("release_timestamp"),
                    "image": {
                      "url": f"https://images.igdb.com/igdb/image/upload/t_1080p/{body.get("poster")}.jpg"
                    }
                  }
                ],
                "attachments": []
            }
        else:
            print(body)
            discord_msg = {
                "content": f"🧩 **New {body.get('game_type') or "DLC / Expansion"} Released!**",
                "embeds": [
                  {
                    "title": body.get("title"),
                    "description": "New downloadable content is now available.",
                    "color": 5814783,
                    "fields": [
                      {
                        "name": "Type",
                        "value": f"`{body.get('game_type') or "Unknown(?)"}`",
                        "inline": True
                      },
                      {
                        "name": "Release Date",
                        "value": f"`{body.get("release_date")}`",
                        "inline": True
                      },
                      {
                        "name": "Expansion Title",
                        "value": f"**{body.get("name")}**"
                      }
                    ],
                    "footer": {
                      "text": "Game DLC Notification"
                    },
                    "timestamp": body.get("release_timestamp"),
                    "thumbnail": {
                      "url": f"https://images.igdb.com/igdb/image/upload/t_1080p/{body.get("poster")}.jpg"
                    }
                  }
                ],
                "attachments": []
            }


        if db_item.get("notifications"):
            requests.post(DISCORD_URL, json=discord_msg)
        return False
    except Exception as e:
      return e

def send_game_to_qstash(delay, body):
    if not delay:
        send_game_notification(body)
    else:
        target_url = "https://media-release-notification.vercel.app/api/notification/game"
        qstash_task_header= {
            "Authorization": f"Bearer {QSTASH_TOKEN}",
            "Content-Type": "application/json",
            "Upstash-Delay": f"{delay}s",
            "Upstash-Forward-Authorization": f"Bearer {os.environ.get('PASSWORD')}"
        }
        qstash_publish_endpoint = f"{QSTASH_URL}/publish/{target_url}"
        qstash_task_payload = body
        requests.post(qstash_publish_endpoint, headers=qstash_task_header, json=qstash_task_payload)
        
def get_data_for_add_item(media_id, media_type):

        movie_response = requests.get(f"https://api.themoviedb.org/3/{media_type}/{media_id}?api_key={TMDB_API_KEY}&append_to_response=external_ids")
        
        
        digital = check_if_digital(media_id)
        movie_data = movie_response.json()
        raw_movie_data = movie_response.json()

        movie_data = {
            "id": movie_data.get("id"),
            "title": movie_data.get("title") or movie_data.get("name"),
            "poster_path": movie_data.get("poster_path"),
            "overview": movie_data.get("overview"),
            "runtime": movie_data.get("runtime") or movie_data.get("episode_run_time") or "",
            "status": movie_data.get("status"),
            "popularity": movie_data.get("popularity"),
            "vote_average": movie_data.get("vote_average"),
            "genres": movie_data.get("genres"),
            "media_type": "movie" if movie_data.get("title") else "tv",
            "last_notification": None,
            "digital": digital,
            "imdb_id": movie_data.get("imdb_id") or None,
            "tvdb_id": None,
            "notifications": True,
            "notifications_enabled_at": datetime.now(timezone.utc).isoformat()
        }
        if media_type == "movie":
            movie_data["release_date"] = raw_movie_data.get("release_date", None)
        else:
            movie_data["first_air_date"] = raw_movie_data.get("first_air_date", None)
            movie_data["last_air_date"] = raw_movie_data.get("last_air_date", None)
            movie_data['next_air_date'] = (raw_movie_data.get('next_episode_to_air') or {}).get("air_date") or None
            
            last_episode_to_air = raw_movie_data.get("last_episode_to_air", {})
            if last_episode_to_air:
                movie_data["last_episode_to_air"] = last_episode_to_air.get("air_date", None)
            else:
                movie_data["last_episode_to_air"] = None

           

            external_ids = raw_movie_data.get("external_ids")
            
            if external_ids.get("imdb_id"):
                movie_data["imdb_id"] = external_ids.get("imdb_id")
            if external_ids.get("tvdb_id"):
                movie_data["tvdb_id"] = external_ids.get("tvdb_id")
            
            is_tvmaze_id = False
            if movie_data.get("imdb_id", ""):
                response = requests.get(f"https://api.tvmaze.com/lookup/shows?imdb={movie_data.get('imdb_id')}")
                if response.status_code == 200:
                    is_tvmaze_id = True
                    tvmaze_data = response.json()
                    movie_data["tvmaze_id"] = tvmaze_data.get("id")
            if not is_tvmaze_id and movie_data.get("tvdb_id", ""):
                response = requests.get(f"https://api.tvmaze.com/lookup/shows?thetvdb={movie_data.get('tvdb_id')}")
                if response.status_code == 200:
                    tvmaze_data = response.json()
                    movie_data["tvmaze_id"] = tvmaze_data.get("id")
                    

                    
        now_iso = datetime.now(timezone.utc).isoformat()
        movie_data["added_date"] = now_iso
        
        update_one_item_in_db(movie_data)
        
        return True
        
@app.route('/api/get-data', methods=['POST'])
def get_watchlist():
    body = request.get_json() or {}
    
    authorized = is_authorized(body)
    if not authorized:
        return jsonify({'error': 'Unauthorized'}), 401
    
    return jsonify(get_db_data_v2()), 200

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

    
    field = f"{movie_type}:{movie_id}"
    requests.post(
    UPSTASH_REDIS_REST_URL,
        headers=headers,
        json=["HDEL", "Watchlist-V2", field]
    )
    return jsonify({"message": f"Removed item with an id of {movie_id}"}), 200

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
        if not media_id or not str(media_id).isdigit() or not (media_type == "tv" or media_type == "movie" or media_type == "game"):
            return jsonify({"error": "Bad Request", "message": "One or more missing required parameters"}), 400

        

        db_data = get_db_data_v2()
        for item in db_data:
            if item.get("media_type") == media_type and item.get("id") == media_id:
                return jsonify({"error": "Unprocessable Entity", "message": "Cannot add item because it is already exists."}), 422
            
        if media_type == "game":
            game = get_game_by_id(media_id)
            db_data.append(game)
            update_db(db_data)
            return jsonify({"success": "true", "message": "Added the media"}), 200


        success = get_data_for_add_item(media_id, media_type)
        if success:
            return jsonify({"success": "true", "message": "Added the media"}), 200
        return jsonify({"error": "something went wrong", "message": "something went wrong while adding the media"}), 500

        # return jsonify({"error": "something went wrong", "message": "something went wrong while adding the media"}), 500
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
        movie_results = []
        tv_results = []
        def get_tmdb_search():
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




            for item in search_results:
                if item.get("media_type") == "tv":
                    tv_results.append(item)
                elif item.get("media_type") == "movie":
                    movie_results.append(item)
        
        
        game_results = []
        def get_game_results():
    

            fields = "name,cover.image_id,first_release_date,game_type,game_status.status,genres.name,hypes,summary,first_release_date,rating,rating_count"
            filters = "themes != (42) & game_type = (0, 8)"

            response = requests.post(f"https://api.igdb.com/v4/games" ,headers=igdb_headers, data=f'fields {fields}; where {filters}; search "{movie_name}";')
            if response.status_code != 200:
                return

            games = response.json()
            for game in games:

                timestamp_raw = game.get("first_release_date")
                release_date = ""
                if timestamp_raw is not None:
                    original_release_date = float(timestamp_raw)
                    release_date = datetime.fromtimestamp(original_release_date, timezone.utc).date().isoformat()

                cover = game.get("cover")
                poster_path = cover.get("image_id", "") if cover else ""

                game_results.append(
                    {
                        "adult": False,
                        'id': game.get("id", ""),
                        "title": game.get("name", ""),
                        "overview": game.get("summary", ""),
                        "poster_path": poster_path,
                        "media_type": "game",
                        "genres": game.get("genres", []),
                        'popularity': game.get("hype", 0),
                        "release_date": release_date,
                        "softcore": False,
                        "video": False,
                        "vote_average": game.get("rating", 0),
                        "vote_count": game.get("rating_count", 0),
                    }
                )    
        
        t1 = threading.Thread(target=get_tmdb_search)
        t2 = threading.Thread(target=get_game_results)
        
        t1.start()
        t2.start()
        
        t1.join()
        t2.join()
        
        if not (movie_results or tv_results or game_results):
            return jsonify({}), 200
        
        ordered_data = {}
        if movie_results:
            ordered_data["movie_results"] = movie_results
        if tv_results:
            ordered_data["tv_results"] = tv_results
        if game_results:
            ordered_data["game_results"] = game_results
            
            
        return jsonify(ordered_data), 200
        

    except KeyError:
        return jsonify({"error": "Bad Request", "message": "something went wrong fetching tmdb data"}), 502

@app.route('/api/checker/movie', methods=['POST'])
def check_movie_v2():
    try:
        db_data = get_db_data_v2()
        id_list = [item.get("id") for item in db_data if (item.get("media_type") == "movie" and not item.get("digital"))]
        if not id_list:
            return jsonify({"success": True, "message": "check_movie checked successfully"}), 200
            
        date_iso = datetime.now(timezone.utc).date().isoformat()

        params = {
        "include_adult": "false",
        "include_video": "false",
        "page": 1,
        "release_date.gte": date_iso,
        "release_date.lte": date_iso,
        "with_release_type": "4|5|6",
        "sort_by": "popularity.desc",
        "api_key": TMDB_API_KEY
        }

        all_movies = []
        page = 1
        total_pages = 1

        while page <= total_pages:
            params["page"] = page
            response = requests.get("https://api.themoviedb.org/3/discover/movie", params=params, timeout=20)
            if response.status_code != 200:
                break
            data = response.json()
            all_movies.extend(data.get("results", []))

            total_pages = data.get("total_pages", 1)
            page += 1

        if all_movies and id_list:
            new_releses = [movie for movie in all_movies if movie.get("id") in id_list]
            print(new_releses)

            if new_releses:
                for movie in new_releses:
                    movie_in_db = [db_movie for db_movie in db_data if movie.get("id") == db_movie.get("id")][0]
                    movie_in_db["digital"] = True
                    movie["notifications"] = movie_in_db.get("notifications")
                    movie["runtime"] = movie_in_db.get("runtime")
                    movie["genres"] = movie_in_db.get("genres")
                    send_movie_notification(movie, datetime.now(timezone.utc).isoformat())
                    update_one_item_in_db(movie_in_db)
        return jsonify({"success": True, "message": "check_movie checked successfully"}), 200
    except Exception as e:
        return jsonify({"error": "Internal Server Error", "message": f"Server error: {e}"}), 500
      
@app.route('/api/notification/tv', methods=['POST'])
def send_tv_notification():
    try:
        auth_header = request.headers.get("authorization", "")
        if not auth_header == f"Bearer {os.environ.get('PASSWORD')}":
            return jsonify({'error': 'Unauthorized'}), 401

        body = request.get_json() or {}


        if len(body) == 1:

            episode = body[0]
            show_id = episode.get("id")
            respons = requests.get(f"https://api.themoviedb.org/3/tv/{show_id}?api_key={TMDB_API_KEY}")
            show_data = {}
            if respons.status_code == 200:
                show_data = respons.json()
            item = get_item_data_from_db({'id': show_id, "media_type": "tv"})

            what_new = "Episode"
            
            if show_data:
                season_number = episode.get("season")
                seasons = show_data.get("seasons") or []
                season_data = next((s for s in seasons if s.get("season_number") == season_number), None)
                if season_data:
                    max_episodes = season_data.get("episode_count")
                    if max_episodes and max_episodes == episode.get("episode"):
                        if max_episodes != 1:
                            what_new = "Season Finale"
                        else:
                            what_new = "Special"
            if what_new != "Special":
                if episode.get("episode") == 1:
                    what_new = "Season"
                    if episode.get("season") == 1:
                        what_new = "Show"
                    

            if episode.get("name") and episode.get("name") != "TBA":

                discord_msg = {
                  "content": f"🎬 **New {what_new} Released!**",
                  "embeds": [
                    {
                      "title": episode.get("show_name"),
                      "description": "A new episode is now streaming.",
                      "color": 15844367,
                      "fields": [
                        {
                          "name": "Season",
                          "value": f"`Season {episode.get("season")}`",
                          "inline": True
                        },
                        {
                          "name": "Episode",
                          "value": f"`Episode {episode.get("episode")}`",
                          "inline": True
                        },
                        {
                          "name": "Episode Title",
                          "value": f"**{episode.get("name")}**",
                          "inline": False
                        }
                      ],
                      "thumbnail": {
                        "url": f"https://image.tmdb.org/t/p/w780{episode.get("poster_path")}"
                      },
                      "footer": {
                        "text": "Episode Release Notification"
                      },
                      "timestamp": f"{episode.get("airstamp")}"
                    }
                  ]
                }

            else:
               discord_msg = {
                  "content": f"🍿 **New {what_new} Available!**",
                  "embeds": [
                    {
                      "title": episode.get("show_name"),
                      "description": "A new episode is now available to watch.",
                      "color": 15844367,
                      "fields": [
                        {
                          "name": "Season",
                          "value": f"`Season {episode.get("season")}`",
                          "inline": True
                        },
                        {
                          "name": "Episode",
                          "value": f"`Episode {episode.get("episode")}`",
                          "inline": True
                        }
                      ],
                      "thumbnail": {
                        "url": f"https://image.tmdb.org/t/p/w780{episode.get("poster_path")}"
                      },
                      "footer": {
                        "text": "Episode Release Notification"
                      },
                      "timestamp": f"{episode.get("airstamp")}"
                    }
                  ]
                }
            if item.get("notifications"):
                requests.post(DISCORD_URL, json=discord_msg)
            return jsonify({"success": "true", "message": "tv notification send successfully"}), 200

        # check if its a new Episodes, Season or Show


            
            
        first_ep = body[0]
        last_ep = body[-1]
        show_id = first_ep.get("id")
        respons = requests.get(f"https://api.themoviedb.org/3/tv/{show_id}?api_key={TMDB_API_KEY}")
        show_data = {}
        if respons.status_code == 200:
            show_data = respons.json()
        what_new = "Episodes"
        new_logic = False
        if show_data:
            season_number = first_ep.get("season")
            seasons = show_data.get("seasons") or []
            season_data = next((s for s in seasons if s.get("season_number") == season_number), None)
            if season_data:
                max_episodes = season_data.get("episode_count")
                if max_episodes:
                    start_ep = first_ep.get("episode")
                    end_ep = last_ep.get("episode")
                    season_num = first_ep.get("season")
                    if end_ep == max_episodes:
                        if start_ep == 1:
                            if season_num == 1:
                                what_new = "Full First Season"
                            else:
                                what_new = "Full Season"
                        else:
                            what_new = "Final Episodes"
                    elif start_ep == 1:
                        if season_num == 1:
                            what_new = "Show"
                        else:
                            what_new = "Season"
                    new_logic = True

                
        if not new_logic:       
            if first_ep.get("episode") == 1:
                what_new = "Season"
                if first_ep.get("season") == 1:
                    what_new = "Show"
        
        item = get_item_data_from_db({'id': first_ep.get("id"), "media_type": "tv"})

        # collect the episodes to an array
        episodes_num = []
        for episode in body:
            episodes_num.append(episode.get("episode"))

        # discoed json msg
        discord_msg = {
              "content": f"🍿 **New {what_new} Available!**",
              "embeds": [
                {
                  "title": f"{first_ep.get("show_name")}",
                  "description": "New episodes are now available to watch.",
                  "color": 15844367,
                  "fields": [
                    {
                      "name": "Season",
                      "value": f"`Season {first_ep.get("season")}`",
                      "inline": True
                    },
                    {
                      "name": "Episodes",
                      "value": f"`Episodes {episodes_num[0]}-{episodes_num[-1]}`",
                      "inline": True
                    }
                  ],
                  "thumbnail": {
                    "url": f"https://image.tmdb.org/t/p/w780{first_ep.get("poster_path")}"
                  },
                  "footer": {
                    "text": "Episode Release Notification"
                  },
                  "timestamp": f"{first_ep.get("airstamp")}"
                }
              ]
            }


        if item.get("notifications"):
            requests.post(DISCORD_URL, json=discord_msg)
        return jsonify({"success": "true", "message": "tv notification send successfully"}), 200
    except Exception as e:
        return jsonify({"success": False, "message": e}), 500
        
@app.route('/api/notification/movie', methods=['POST'])
def prepper_to_send_movie_notification():
    
    auth_header = request.headers.get("authorization", "")
    if not auth_header == f"Bearer {os.environ.get('PASSWORD')}":
        return jsonify({'error': 'Unauthorized'}), 401
   
    body = request.get_json() or {}
    
    movie = body['show_info']
    
    time = datetime.now(timezone.utc).isoformat()
    

    response = requests.get(f"https://api.themoviedb.org/3/movie/{movie['id']}/release_dates?api_key={TMDB_API_KEY}")
    data = response.json()
    results = data.get('results' , [])
    movie_notification_now = False
    
    for country in results:
        if country.get('release_dates', []):
            for dates in country['release_dates']:
                if dates['type'] >= 4 and datetime.fromisoformat(dates['release_date']).date() <= datetime.now(timezone.utc).date():
                    movie_notification_now = True
    
    movie['notification_soon'] = False
    if movie_notification_now:
        movie['digital'] = True
        if movie.get("notifications"):
            send_movie_notification(movie, time)

    update_one_item_in_db(movie)
        
    
    
    
    
    
    
    
    
    return jsonify({"success": "true", "message": "movie notification send successfully"}), 200

@app.route('/api/checker/tv', methods=['POST'])
def check_tv_v2():
    
    
    
    try:
        auth_header = request.headers.get("authorization", "")
        if not auth_header == f"Bearer {os.environ.get('PASSWORD')}":
            return jsonify({'error': 'Unauthorized'}), 401
        db_data = get_db_data_v2()
        id_list = [item.get("tvmaze_id") for item in db_data if (item.get("media_type") == "tv" and item.get("tvmaze_id", ""))]
        date_iso = datetime.now(timezone.utc).date().isoformat()

        response = requests.get(f"https://api.tvmaze.com/schedule/?date={date_iso}")
        response_web = requests.get(f"https://api.tvmaze.com/schedule/web?date={date_iso}&country=")
        data = response.json() or []
        data_web = response_web.json() or []
        new_ep = []
        if data or data_web:
            for ep in data + data_web:
                if ((((ep.get("show") or {}).get("id") or "") or (((ep.get("_embedded") or {}).get("show") or {}).get("id") or "")) in id_list):
                    new_ep.append(ep)
            if new_ep:
                new_ep_formated = []
                for ep in new_ep:
                    tvmaze_id = (((ep.get("show") or {}).get("id") or "") or (((ep.get("_embedded") or {}).get("show") or {}).get("id") or ""))
                    show_id = [item["id"] for item in db_data if item.get("tvmaze_id") == tvmaze_id]
                    poster_path = [item["poster_path"] for item in db_data if item.get("tvmaze_id") == tvmaze_id]
                    
                    show_time_stemp = datetime.fromisoformat(ep.get("airstamp") or f"{ep.get('airdate')}T12:00:00+00:00")
                    if not ep.get("airtime"):
                        # Fallback default (Netflix, HBO Max, Paramount+ -> 07:00 UTC)
                        show_time_stemp = show_time_stemp.replace(hour=7)
                        show_path = ep.get("show") or ep.get("_embedded", {}).get("show", {})
                        web_channel_obj = show_path.get("webChannel") or ep.get("webChannel") or {}
                        web_channel = web_channel_obj.get("name") if isinstance(web_channel_obj, dict) else None
                        if web_channel:
                            if web_channel == "Prime Video":
                                show_time_stemp = show_time_stemp.replace(hour=0)
                            elif web_channel == "Apple TV":
                                show_time_stemp = show_time_stemp.replace(hour=1)
                            elif web_channel == "Disney+":
                                show_time_stemp = (show_time_stemp + timedelta(days=1)).replace(hour=1)
                            elif web_channel == "Hulu":
                                show_time_stemp = show_time_stemp.replace(hour=4)
                            elif web_channel == "Peacock":
                                show_time_stemp = show_time_stemp.replace(hour=9)

                                
                    
                    new_ep_formated.append({
                        "id": show_id[0],
                        "show_name": (((ep.get("show") or {}).get("name") or "") or (((ep.get("_embedded") or {}).get("show") or {}).get("name") or "")),
                        "season": ep.get("season"),
                        "episode": ep.get("number"),
                        "airstamp": show_time_stemp.isoformat(),
                        "type": ep.get("type"),
                        "name": ep.get("name"),
                        "poster_path": poster_path[0],
                    })


                new_ep_by_show = {}

                for ep in new_ep_formated:
                    show_id = str(ep.get("id"))
                    if show_id not in new_ep_by_show:
                        new_ep_by_show[show_id] = []
                    new_ep_by_show[show_id].append(ep)

                list_new_ep_by_show = list(new_ep_by_show.values())

                target_url = "https://media-release-notification.vercel.app/api/notification/tv"


                for show in list_new_ep_by_show:

                    show_time_stemp = datetime.fromisoformat(show[0].get("airstamp") or "1970-01-01T12:00:00+00:00")
                    now_time_stemp = datetime.now(timezone.utc)
                    seconds_left = int(max(0, show_time_stemp.timestamp() - now_time_stemp.timestamp())) 

                    qstash_task_header= {
                        "Authorization": f"Bearer {QSTASH_TOKEN}",
                        "Content-Type": "application/json",
                        "Upstash-Delay": f"{seconds_left}s",
                        "Upstash-Forward-Authorization": f"Bearer {os.environ.get('PASSWORD')}"
                    }

                    qstash_publish_endpoint = f"{QSTASH_URL}/publish/{target_url}"
                    qstash_task_payload = show
                    response = requests.post(qstash_publish_endpoint, headers=qstash_task_header, json=qstash_task_payload)
        return jsonify({"success": "true", "message": "check_tv notification successfully"}), 200
        
    except Exception as e:
        return jsonify({"error": "Bad Gateway", "message": f"Server error: {e}"}), 502
    
@app.route('/api/updater', methods=['POST'])
def updater():
    
    auth_header = request.headers.get("authorization", "")
    if not auth_header == f"Bearer {os.environ.get('PASSWORD')}":
        return jsonify({'error': 'Unauthorized'}), 401
    
    db_data = get_db_data_v2()
    limit = 20
    tvmaze_limit = 10
    for item in db_data:
        if not limit:
            break
        
        
        if ((not item.get('last_updated')) or datetime.fromisoformat(item.get('last_updated')).date() != datetime.now(timezone.utc).date()) and item.get('media_type', "") != "game":
            
            if item['media_type'] == "tv" and not item.get("tvmaze_id"):
                if not tvmaze_limit:
                    continue
                if item.get("imdb_id"):
                    response = requests.get(f"https://api.tvmaze.com/lookup/shows?imdb={item.get("imdb_id")}")
                    tvmaze_limit -= 1
                    if response.status_code == 200:
                        tvmaze_data = response.json()
                        item["tvmaze_id"] = tvmaze_data.get("id")
            
            response = requests.get(f"https://api.themoviedb.org/3/{item['media_type']}/{item['id']}?api_key={TMDB_API_KEY}&append_to_response=release_dates,external_ids")
            data = response.json()
            
            limit -= 1
            item["title"] = data.get('title') or data.get('name') or ""
            item['poster_path'] = data.get('poster_path') or ""
            item['overview'] = data.get('overview') or ""
            item['runtime'] = data.get('runtime') or data.get('episode_run_time') or ""
            item['status'] = data.get('status') or ""
            item['genres'] = data.get('genres', "") or ""
            item['vote_average'] = data.get('vote_average', "") or 0
            item['popularity'] = data.get('popularity', "") or 0
                
            if item.get('release_date', "") !=  data.get('release_date', ""):
                item['release_date'] = data.get('release_date', "")
                
            if item.get('first_air_date', "") !=  data.get('first_air_date', ""):
                item['first_air_date'] = data.get('first_air_date', "")

            if item.get('media_type', "") == "tv":
                item['last_air_date'] = data.get('last_air_date', "")
                item['next_air_date'] = (data.get('next_episode_to_air') or {}).get("air_date") or None


            item['imdb_id'] = data.get('imdb_id') or (data.get('external_ids') or {}).get("imdb_id") or ""
                
            item['last_updated'] = datetime.now(timezone.utc).isoformat()
           
            try:
                if item.get('media_type', "") == "movie":
                    release_dates = (data.get('release_dates') or {}).get('results')
                    if release_dates:
                        if not item.get('digital'):
                            for date in release_dates:
                                date_obj = (date.get('release_dates')[0] or {})
                                if date_obj.get("type") > 3:
                                    release_date = datetime.fromisoformat(date_obj.get("release_date"))
                                    if release_date < datetime.now(timezone.utc):
                                        is_digital = True
                                        item["digital"] = True
                                        send_movie_notification(item, datetime.now(timezone.utc).isoformat())
                                        break
                                
                        all_release_dates = []
                        for country in release_dates:
                            for date_obj in country.get('release_dates', []):
                                if date_obj.get('release_date'):
                                    all_release_dates.append(date_obj)
                        all_release_dates.sort(key=lambda _: _.get('release_date'))
                        first_theatrical_release = ""
                        first_digital_release = ""
                        for release_date in all_release_dates:
                            if release_date.get('type') <= 3:
                                first_theatrical_release = release_date.get('release_date')
                                break
                        for release_date in all_release_dates:
                            if release_date.get('type') > 3:
                                first_digital_release = release_date.get('release_date')
                                break
                        if first_theatrical_release:
                            item["theatrical_release"] = first_theatrical_release
                        if first_digital_release:
                            item["digital_release"] = first_digital_release
                        
            except Exception:
                continue
                 
    update_db(db_data)
    return jsonify({"success": True, "message": "Updated the media"}), 200

@app.route('/api/updater/game', methods=['POST'])
def game_updater():
    try: 
        auth_header = request.headers.get("authorization", "")
        if not auth_header == f"Bearer {os.environ.get('PASSWORD')}":
            return jsonify({'error': 'Unauthorized'}), 401

        watchlist = get_db_data_v2()
        limit = 18
        items_before_sleeping = 3
        sleep_for = 2

        count = 0

        for item in watchlist:
            if count == limit:
                break

            if item.get("media_type") == "game" and (not item.get("last_updated") or datetime.fromisoformat(item.get("last_updated")).date() != datetime.now(timezone.utc).date()):

                if count and count % items_before_sleeping == 0:
                    time.sleep(sleep_for)

                fields = (
                        "name,cover.image_id,first_release_date,game_type,game_status,genres.name,hypes,summary,rating,rating_count,"
                        "involved_companies.company.name,involved_companies.developer,involved_companies.publisher,"
                        "platforms.abbreviation,"
                        "release_dates.status.name,release_dates.date,"
                        "dlcs.name,dlcs.first_release_date,dlcs.game_type.type,dlcs.cover.image_id,"
                        "expanded_games.name,expanded_games.first_release_date,expanded_games.game_type.type,expanded_games.cover.image_id,"
                        "expansions.name,expansions.first_release_date,expansions.game_type.type,expansions.cover.image_id,"
                        "ports.name,ports.first_release_date,ports.game_type.type,ports.cover.image_id,"
                        "remakes.name,remakes.first_release_date,remakes.game_type.type,remakes.cover.image_id,"
                        "remasters.name,remasters.first_release_date,remasters.game_type.type,remasters.cover.image_id,"
                        "standalone_expansions.name,standalone_expansions.first_release_date,standalone_expansions.game_type.type,standalone_expansions.cover.image_id"
                    )
                response = requests.post(f"https://api.igdb.com/v4/games" ,headers=igdb_headers, data=f'fields {fields}; where id = {item["id"]};')
                count += 1
                data = response.json()
                if not data:
                    continue
                game = data[0]

                item["last_updated"] = datetime.now(timezone.utc).isoformat()

                item_timestamp_raw = game.get("first_release_date")
                item_release_date = ""
                if item_timestamp_raw is not None:
                    item_original_release_date = float(item_timestamp_raw)
                    item_release_date = datetime.fromtimestamp(item_original_release_date, timezone.utc).date().isoformat()
                item["release_date"] = item_release_date
                item["title"] = game.get("name") or ""
                item["poster_path"] = (game.get("cover") or {}).get("image_id") or ""
                item["overview"] = game.get("summary") or ""
                item["genres"] = game.get("genres") or []
                item["popularity"] = game.get("hypes") or 0
                item["vote_average"] = game.get("rating") or 0
                item["vote_count"] = game.get("rating_count") or 0

                update_one_item_in_db(item)
        return jsonify({"success": True, "message": "game_updater run successfully"}), 200
    except Exception as e:
        return jsonify({"success": False, "message": f"{e}"}), 500

@app.route('/api/checker/game', methods=['POST'])
def get_new_games():
    try: 
        
        auth_header = request.headers.get("authorization", "")
        if not auth_header == f"Bearer {os.environ.get('PASSWORD')}":
            return jsonify({'error': 'Unauthorized'}), 401
        
        today = datetime.now(timezone.utc).date().isoformat()
        db_data = get_db_data_v2()
        id_list = [game.get("id") for game in db_data if game.get("media_type", "") == "game" and game.get("last_notified", "") != today]

        now = datetime.now(timezone.utc)
        start_of_today = int(now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
        end_of_today = int(now.replace(hour=23, minute=59, second=59, microsecond=999999).timestamp())



        fields = (  
                "platform.abbreviation, date, status,"
                "game.name, game.game_type.type, game.involved_companies.developer, game.involved_companies.company.name, game.genres.name, game.cover.image_id,"
                "game.parent_game,game.parent_game.name, game.parent_game.cover.image_id;"
                f"where date >= {start_of_today} & date <= {end_of_today}; "
                "sort date asc; "
                "limit 500;"
            )
        response = requests.post(f"https://api.igdb.com/v4/release_dates" ,headers=igdb_headers, data=f'fields {fields}')

        data = response.json()
        if data:
            all_new_games = []
            for resolt in data:
                if resolt.get("id") in id_list or (resolt.get("game") or {}).get('id') in id_list or ((resolt.get("game") or {}).get('parent_game') or {}).get("id") in id_list:
                    all_new_games.append(resolt)

            if all_new_games:
                new_games = {}
                for new_game in all_new_games:
                    game_id = (new_game.get("game") or {}).get("id")
                    if not new_games.get(game_id):
                        new_games[game_id] = []
                    new_games[game_id].append(new_game)
                new_games = list(new_games.values())
                for new_game in new_games:
                    candidate_ids = [
                        ((new_game[0].get("game") or {}).get("parent_game") or {}).get("id"),
                        (new_game[0].get("game") or {}).get("id"),
                        new_game[0].get("id")
                    ]
                    matched_db_id = next((candidate_id for candidate_id in candidate_ids if candidate_id in id_list), None)
                    name = new_game[0].get('game', {}).get("name", "")
                    raw_platforms = [
                        item.get("platform", {}).get("abbreviation") or item.get("platform", {}).get("name", "")
                        for item in new_game
                    ]
                    platforms = sorted(set(raw_platforms), key=lambda platform: (0 if platform == "PC" else 1, platform))
                    title = (new_game[0].get("game", {}).get("parent_game") or {}).get("name", "") or new_game[0].get("game", {}).get("name", "")
                    game_type = new_game[0].get("game", {}).get("game_type", {}).get("type", "")
                    game_type_id = new_game[0].get("game", {}).get("game_type", {}).get("id", "")
                    release_date = datetime.fromtimestamp(new_game[0].get("date"), timezone.utc)
                    involved = new_game[0].get("game", {}).get("involved_companies") or []
                    developer = [item.get("company", {}).get("name", "") for item in involved if item.get("developer")]
                    developer = developer[0] if developer else ""
                    cover = (new_game[0].get("game", {}).get("cover") or {}).get("image_id", "")
                    parent_cover = ((new_game[0].get("game", {}).get("parent_game") or {}).get("cover") or {}).get("image_id", "")
                    poster = cover or parent_cover
                    genres_list = new_game[0].get("game", {}).get("genres") or []
                    genres = [item.get("name") for item in genres_list]
                    body = {
                        "id": matched_db_id,
                        "media_type": "game",
                        "title": title,
                        "platforms": platforms,
                        "game_type": game_type,
                        "name": name,
                        "game_type_id": game_type_id,
                        "release_date": release_date.date().isoformat(),
                        "release_timestamp": release_date.isoformat(),
                        "developer": developer,
                        "genres": genres,
                        "poster": poster,
                    }
                    db_item = next(item for item in db_data if item.get("id") == matched_db_id)
                    db_item["last_notified"] = today
                    update_one_item_in_db(db_item)
                    delay = max(int(release_date.timestamp() - datetime.now(timezone.utc).timestamp()), 0)
                    send_game_to_qstash(delay, body)

        return jsonify({"success": "true", "message": "check_game checked successfully"}), 200
    except Exception as e:
        return jsonify({"success": "false", "message": f"{e}"}), 500

@app.route('/api/notification/game', methods=['POST'])
def get_game_notification():
        auth_header = request.headers.get("authorization", "")
        if not auth_header == f"Bearer {os.environ.get('PASSWORD')}":
            return jsonify({'error': 'Unauthorized'}), 401
        
        body = request.get_json() or {}
        faild = send_game_notification(body)
        if not faild:
            return jsonify({"success": True, "message": "game notification send successfully"}), 200
        
        return jsonify({"success": False, "message": f"{faild}"}), 500

@app.route('/api/toggle/notification', methods=['POST'])
def toggle_notification():
    
    body = request.get_json() or {}
    authorized = is_authorized(body)
    if not authorized:
        return jsonify({'error': 'Unauthorized'}), 401
    
    getting_item = {'id': body.get("movieId"), "media_type": body.get("movieType")}
    
    item = get_item_data_from_db(getting_item)
    if item:
        if body.get("notifications_enabled"):
            item["notifications"] = True
            item["notifications_enabled_at"] = datetime.now(timezone.utc).isoformat()
        else:
            item["notifications"] = False
        update_one_item_in_db(item)
        return jsonify({"success": "true", "notification_status": item["notifications"]}), 200

    else:
        return jsonify({"success": "false", "notification_status": "unknown"}), 500 
    
@app.route('/api/info/movie', methods=['POST'])
def get_movie_info():
    
    body = request.get_json() or {}
    authorized = is_authorized(body)
    if not authorized:
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        movie_id = body.get("movieId") or ""
        if not movie_id:
            return jsonify({"error": "misiing id"})

        response = requests.get(f"https://api.themoviedb.org/3/movie/{movie_id}?api_key={TMDB_API_KEY}&append_to_response=keywords,release_dates,videos,credits")
        data = response.json()

        movie = {
            "title": data.get("title", ""),
            "poster_path": data.get("poster_path", ""),
            "backdrop_path": data.get("backdrop_path", ""),
            "release_date": data.get("release_date", ""),
            "runtime": data.get("runtime", 0),
            "vote_average": data.get("vote_average", 0.0),
            "vote_count": data.get("vote_count", 0),
            "status": data.get("status", ""),
            "budget": data.get("budget", 0),
            "revenue": data.get("revenue", 0),
            "genres": data.get("genres", []),
            "tagline": data.get("tagline", ""),
            "overview": data.get("overview", ""),
            "production_companies": data.get("production_companies", []),
            "origin_country": data.get("origin_country", []),
            "original_language": data.get("original_language", ""),
            "homepage": data.get("homepage", ""),
            "id": data.get("id", ""),
            "imdb_id": data.get("imdb_id", ""),
            "keywords": (data.get("keywords") or {}).get("keywords") or [],
        }

        # digital and expected_on_digital if not digital
        next_digital_date = "Unknown(?)"
        digital = False
        try:
            dates = (data.get("release_dates") or {}).get('results') or []
            digital_dates = []
            if dates:
                for country in dates:
                    if country.get('release_dates', []):
                        for date in country['release_dates']:
                            if date['type'] >= 4:
                                digital_dates.append(date)


            if digital_dates:
                for digital_date in digital_dates:
                    if digital_date.get('release_date') and datetime.fromisoformat(digital_date.get('release_date')) <= datetime.now(timezone.utc):
                        digital = True
                        break
                if digital:
                    movie["digital"] = True
                else:
                    movie["digital"] = False
                    # gets the first date
                    next_digital_date = sorted(digital_dates, key=lambda date: date['release_date'])[0]
                    # convert the first date in to a date
                    next_digital_date = datetime.fromisoformat(next_digital_date["release_date"]).date().isoformat()
                    # add to the movie obj
                    movie["expected_on_digital"] = next_digital_date
                    
            
        except Exception as e:
            ...
        movie["digital"] = digital

        # videos 
        videos = (data.get("videos") or {}).get("results") or []
        if videos:
            trailers = [video for video in videos if video["site"] == 'YouTube' and video["type"] == 'Trailer'] or []
            if not trailers:
                teasers = [video for video in videos if video["site"] == 'YouTube' and video["type"] == 'Teaser'] or []
                if teasers:
                    teasers = sorted(teasers, key=lambda vid: vid["published_at"])
                    movie["teasers"] = teasers
            else:
                trailers = sorted(trailers, key=lambda vid: vid.get("published_at"))
                movie["trailers"] = trailers
                
                
        credits = data.get("credits") or {}
        if credits:
            cast = credits.get("cast") or []
            cast = [actor for actor in cast if actor.get("known_for_department") == "Acting"]
            if cast:
                new_cast = []
                for actor in cast[:30]:
                    new_cast.append({
                        'id': actor.get("id"),
                        'name': actor.get("name"),
                        'profile_path': actor.get("profile_path"),
                        'character': actor.get("character")
                    })
                movie["cast"] = new_cast
        
            crew = credits.get("crew") or []
            if crew:
                director = [member for member in crew if member.get("job", "") == "Director"]
                directors = []
                if director:
                    for person in director:
                        directors.append({
                            'id': person.get("id"),
                            'name': person.get("name"),
                            'name': person.get("name"),
                            'profile_path': person.get("profile_path"),
                        })
                    if directors:
                        movie["directors"] = directors

        response = requests.get(f"https://api.themoviedb.org/3/movie/{movie_id}/watch/providers?api_key={TMDB_API_KEY}")

        providers_results = response.json().get('results') or {}
        providers_data = {}
        if providers_results:
            print(providers_results)
            origin_country = data.get("origin_country")
            if origin_country:
                origin_country = origin_country[0]
            if origin_country:
                origin_country_data = providers_results.get(origin_country) or {}
                if origin_country_data:
                    providers_data[origin_country] = origin_country_data
            if origin_country != "US":
                us_data = providers_results.get("US") or {}
                if us_data:
                    providers_data["US"] = us_data

            if providers_data: 
                movie["watch_providers"] = providers_data

                us_release_dates = ""
                
        age_rating = ""
        release_dates = (data.get("release_dates") or {}).get("results")
        if release_dates:
            us_release_dates = [country for country in release_dates if country.get("iso_3166_1") == "US"]
            if us_release_dates:
                us_release_dates = us_release_dates[0].get('release_dates') or {}
                if us_release_dates:
                    for release_date in us_release_dates:
                        certification = ""
                        if (release_date.get('certification') or ""):
                            certification = release_date.get('certification') or {}
                            if certification:
                                age_rating = certification
                                break
        if age_rating:
            movie["age_rating"] = age_rating


        return jsonify(movie), 200
    except Exception as e:
        return jsonify({"success": False, "message": f"{e}"}), 500

@app.route('/api/info/tv', methods=['POST'])
def get_tv_info():
    try:
        body = request.get_json() or {}
        authorized = is_authorized(body)
        if not authorized:
            return jsonify({'error': 'Unauthorized'}), 401

        tv_id = body.get("showId") or ""
        if not tv_id:
            return jsonify({"error": "misiing id"})

        response = requests.get(f"https://api.themoviedb.org/3/tv/{tv_id}?api_key={TMDB_API_KEY}&append_to_response=keywords,release_dates,videos,credits,content_ratings,external_ids")
        data = response.json()
        show = {
            "title": data.get("name", ""),
            "poster_path": data.get("poster_path", ""),
            "backdrop_path": data.get("backdrop_path", ""),
            "release_date": data.get("first_air_date", ""),
            "last_air_date": data.get("last_air_date", ""),
            "next_air_date": (data.get("next_episode_to_air") or {}).get("air_date", None),
            "runtime": data.get("episode_run_time", 0),
            "vote_average": data.get("vote_average", 0.0),
            "vote_count": data.get("vote_count", 0),
            "status": data.get("status", ""),
            "budget": data.get("budget", 0),
            "revenue": data.get("revenue", 0),
            "genres": data.get("genres", []),
            "tagline": data.get("tagline", ""),
            "overview": data.get("overview", ""),
            "number_of_episodes": data.get("number_of_episodes", 0),
            "number_of_seasons": data.get("number_of_seasons", 0),
            "production_companies": data.get("production_companies", []),
            "origin_country": data.get("origin_country", []),
            "original_language": data.get("original_language", ""),
            "homepage": data.get("homepage", ""),
            "id": data.get("id", ""),
            "imdb_id": data.get("imdb_id", ""),
            "keywords": (data.get("keywords") or {}).get("keywords") or [],
        }


        # videos 
        videos = (data.get("videos") or {}).get("results") or []
        if videos:
            trailers = [video for video in videos if video["site"] == 'YouTube' and video["type"] == 'Trailer'] or []
            if not trailers:
                teasers = [video for video in videos if video["site"] == 'YouTube' and video["type"] == 'Teaser'] or []
                if teasers:
                    teasers = sorted(teasers, key=lambda vid: vid["published_at"])
                    show["teasers"] = teasers
            else:
                trailers = sorted(trailers, key=lambda vid: vid.get("published_at"))
                show["trailers"] = trailers

        credits = data.get("credits") or {}
        if credits:
            cast = credits.get("cast") or []
            cast = [actor for actor in cast if actor.get("known_for_department") == "Acting"]
            if cast:
                new_cast = []
                for actor in cast[:30]:
                    new_cast.append({
                        'id': actor.get("id"),
                        'name': actor.get("name"),
                        'profile_path': actor.get("profile_path"),
                        'character': actor.get("character")
                    })
                show["cast"] = new_cast

            crew = credits.get("crew") or []
            if crew:
                director = [member for member in crew if member.get("job", "") == "Director"]
                directors = []
                if director:
                    for person in director:
                        directors.append({
                            'id': person.get("id"),
                            'name': person.get("name"),
                            'name': person.get("name"),
                            'profile_path': person.get("profile_path"),
                        })
                    if directors:
                        show["directors"] = directors


        response = requests.get(f"https://api.themoviedb.org/3/tv/{tv_id}/watch/providers?api_key={TMDB_API_KEY}")
        providers_results = response.json().get('results') or {}
        providers_data = {}
        if providers_results:
            origin_country = data.get("origin_country")
            if origin_country:
                origin_country = origin_country[0]
            if origin_country:
                origin_country_data = providers_results.get(origin_country) or {}
                if origin_country_data:
                    providers_data[origin_country] = origin_country_data
            if origin_country != "US":
                us_data = providers_results.get("US") or {}
                if us_data:
                    providers_data["US"] = us_data

            if providers_data: 
                show["watch_providers"] = providers_data


        # response = requests.get(f"https://api.themoviedb.org/3/tv/{data.get('id')}/external_ids?api_key={TMDB_API_KEY}")
        external_ids = data.get('external_ids') or {}
        if external_ids.get("imdb_id"):
            show["imdb_id"] = external_ids.get("imdb_id")
        if external_ids.get("tvdb_id"):
            show["tvdb_id"] = external_ids.get("tvdb_id")


        tvmaze_id = body.get("tvmazeid") or ""
        if not tvmaze_id:
            if show.get("imdb_id"):
                response = requests.get(f"https://api.tvmaze.com/lookup/shows?imdb={show.get('imdb_id')}")
                if response.status_code == 200:
                    tvmaze_data = response.json()
                    show["tvmaze_id"] = tvmaze_data.get("id")
            if not show.get("tvmaze_id") and show.get("tvdb_id", ""):
                response = requests.get(f"https://api.tvmaze.com/lookup/shows?thetvdb={show.get('tvdb_id')}")
                if response.status_code == 200:
                    tvmaze_data = response.json()
                    show["tvmaze_id"] = tvmaze_data.get("id")
        else:
            show["tvmaze_id"] = tvmaze_id

        if show.get("tvmaze_id"):
            print(show.get("tvmaze_id"))

            response = requests.get(f"https://api.tvmaze.com/shows/{show.get("tvmaze_id")}/episodes?specials=1")
            episodes = response.json()
            if episodes:
                show_tvmaze_data = requests.get(f"https://api.tvmaze.com/shows/{show.get("tvmaze_id")}").json()
                for episode in episodes:
                    airstamp = datetime.fromisoformat(episode.get("airstamp") or f"{episode.get('airdate')}T12:00:00+00:00")
                    if not episode.get("airtime"):
                        airstamp = airstamp.replace(hour=7)
                        web_channel = (show_tvmaze_data.get("webChannel") or {}).get("name")
                        if web_channel:
                            if web_channel == "Prime Video":
                                airstamp = airstamp.replace(hour=0)
                            elif web_channel == "Apple TV":
                                airstamp = airstamp.replace(hour=1)
                            elif web_channel == "Disney+":
                                airstamp = (airstamp + timedelta(days=1)).replace(hour=1)
                            elif web_channel == "Hulu":
                                airstamp = airstamp.replace(hour=4)
                            elif web_channel == "Peacock":
                                airstamp = airstamp.replace(hour=9)
                    episode["airstamp"] = airstamp
                show["episodes"] = episodes


        age_rating = ""
        raw_age_ratings = (data.get("content_ratings") or {}).get("results")
        if raw_age_ratings:
            for rating in raw_age_ratings:
                if rating.get("iso_3166_1") == "US":
                    raw_age_rating = rating.get("rating") or ""
                    if raw_age_rating:
                        age_rating = raw_age_rating
                        break

        if age_rating:
            show["age_rating"] = age_rating

        return jsonify(show), 200
    except Exception as e:
        return jsonify({"success": False, "message": f"{e}"}), 500

@app.route('/api/info/game', methods=['POST'])
def get_game_info():
    try:
        body = request.get_json() or {}
        authorized = is_authorized(body)
        if not authorized:
            return jsonify({'error': 'Unauthorized'}), 401
        game_id = body.get("gameid") or ""
        if not game_id:
            return jsonify({"error": "misiing id"})

        fields = "name, url, first_release_date, cover.image_id, artworks.image_id, artworks.image_type, rating, game_status.status, rating, rating_count, genres.name, summary, storyline, involved_companies.company.name, involved_companies.company.logo.image_id, involved_companies.company.url, involved_companies.company.country, involved_companies.developer, involved_companies.porting, involved_companies.publisher, involved_companies.supporting, language_supports.language.name, language_supports.language_support_type, websites.url, websites.type.type, keywords.name, age_ratings.rating_category.rating, age_ratings.organization.name, game_type.type, franchises.name, franchises.url, game_engines.name, game_engines.logo.image_id, game_modes.name, parent_game.name, parent_game.cover.image_id, platforms.abbreviation, platforms.platform_logo.image_id, player_perspectives.name, videos.*, bundles.name, bundles.cover.image_id, bundles.game_type, bundles.first_release_date, dlcs.name, dlcs.cover.image_id, dlcs.game_type, dlcs.first_release_date, expansions.name, expansions.cover.image_id, expansions.game_type, expansions.first_release_date, ports.name, ports.cover.image_id, ports.game_type, ports.first_release_date, remakes.name, remakes.cover.image_id, remakes.game_type, remakes.first_release_date, remasters.name, remasters.cover.image_id, remasters.game_type, remasters.first_release_date"
        filters = f"id = {game_id}"
        response = requests.post("https://api.igdb.com/v4/games", headers=igdb_headers, data=f"fields {fields}; where {filters}; limit 50;")
        data = response.json()
        if len(data) >= 1:
            game_data = data[0]
        else:
            return jsonify({"error": "no info found"}), 404

        release_date = ""
        release_date_raw = ""
        if game_data.get("first_release_date"):
            release_date_raw = datetime.fromtimestamp(game_data.get("first_release_date"), timezone.utc)
            if release_date_raw:
                release_date = release_date_raw.date().isoformat()

        backdrop_path = next((item.get('image_id') for item in (game_data.get("artworks") or []) if item.get("image_type") == 2), "") or next((item.get('image_id') for item in (game_data.get("artworks") or []) if item.get("image_type") == 3), "")

        game_status = (game_data.get("game_status") or {}).get("status")

        if not game_status:
            if not release_date_raw or release_date_raw > datetime.now(timezone.utc):
                game_status = "Upcoming"
            else: 
                game_status = "Released"

        original_language = game_data.get("language_supports", [])
        if original_language:
            original_language = [(item.get("language") or {}).get('name') for item in original_language if item.get("language_support_type") == 1]

        websites = game_data.get("websites", "")
        homepage = ""
        if websites:
            homepage = next((item.get("url") for item in websites if (item.get('type') or {}).get('id') == 1), "")

        keywords = []
        if game_data.get("keywords", []):
            keywords = [item.get("name") for item in game_data.get("keywords")]

        age_ratings = game_data.get("age_ratings", [])
        if age_ratings:
            age_ratings = [{"organization": (item.get("organization") or {}).get('name', "?"), "rating": (item.get("rating_category") or {}).get('rating', "?")} for item in age_ratings]

        franchises = game_data.get("franchises")
        if franchises:
            franchises = [{"name": item.get("name", ""), "url": item.get("url", "")} for item in franchises]

        game_engines = game_data.get("game_engines", [])
        if game_engines:
            game_engines = [{"name": item.get("name", ""), "image_path": (item.get("logo") or {}).get('image_id')} for item in game_engines]

        platforms = game_data.get("platforms", [])
        if platforms:
            platforms = [{"abbreviation": item.get("abbreviation", ""), "platform_logo": (item.get("platform_logo") or {}).get('image_id')} for item in platforms]

        videos = game_data.get("videos")
        if videos:
            videos = [{"name": item.get("name", ""), "video_id": item.get("video_id") or {}} for item in videos]

        involved_companies = game_data.get("involved_companies", [])
        if involved_companies:
            for company in involved_companies:
                country = ""
                try:
                    country = countries.get((company.get("company") or {}).get("country")).alpha2
                except Exception:
                    pass
                company_info = {"name": (company.get("company") or {}).get("name", ""), "logo_path": ((company.get("company") or {}).get('logo') or {}).get('image_id'), "url": (company.get("company") or {}).get("url", ""), "country": country}
                company["company"] = company_info

        stores = []
        if websites:
            stores = [{"name": (item.get("type") or {}).get('type', "?"), "url": item.get("url")} for item in websites if (item.get("type") or {}).get('id') == 10 or (item.get("type") or {}).get('id') == 11 or (item.get("type") or {}).get('id') == 12 or (item.get("type") or {}).get('id') == 13 or (item.get("type") or {}).get('id') == 16 or (item.get("type") or {}).get('id') == 17]

        links = []
        if websites:
            links = [{"name": (item.get("type") or {}).get('type', "?"), "url": item.get("url")} for item in websites if (item.get("type") or {}).get('id') == 2 or (item.get("type") or {}).get('id') == 3 or (item.get("type") or {}).get('id') == 4 or (item.get("type") or {}).get('id') == 5 or (item.get("type") or {}).get('id') == 6 or (item.get("type") or {}).get('id') == 8 or (item.get("type") or {}).get('id') == 9 or (item.get("type") or {}).get('id') == 14 or (item.get("type") or {}).get('id') == 18 or (item.get("type") or {}).get('id') == 19]


        bundles = game_data.get("bundles") or []
        dlcs = game_data.get("dlcs") or []
        expansions = game_data.get("expansions") or []
        ports = game_data.get("ports") or []
        remakes = game_data.get("remakes") or []
        remasters = game_data.get("remasters") or []
        for item in bundles + dlcs + expansions + ports + remakes + remasters:
            first_release_date = item.get("first_release_date")
            if first_release_date:
                item["first_release_date"] = datetime.fromtimestamp(item.get("first_release_date")).date().isoformat()
            cover = (item.get("cover") or {}).get("image_id")
            if cover:
                item['cover'] = cover

        origin_country = ""
        if involved_companies:
            origin_country = [(item.get('company') or {}).get('country') for item in involved_companies if item.get('developer')]

        game = {
            "title": game_data.get("name", ""),
            "poster_path": (game_data.get("cover") or {}).get("image_id"),
            "backdrop_path": backdrop_path,
            "release_date": release_date,
            "vote_average": game_data.get("rating", 0.0),
            "vote_count": game_data.get("rating_count", 0),
            "status": game_status,
            "genres": game_data.get("genres", []),
            "overview": game_data.get("summary", ""),
            "storyline": game_data.get("storyline", ""),
            "involved_companies": involved_companies,
            "origin_country": origin_country,
            "original_language": original_language,
            "homepage": homepage,
            "id": game_data.get("id", ""),
            "keywords": keywords,
            "age_ratings": age_ratings,
            "game_type": (game_data.get("game_type") or {}).get('type'),
            "franchise": franchises,
            "game_engines": game_engines,
            "game_modes": game_data.get("game_modes", []),
            "parent_game": game_data.get("parent_game"),
            "platforms": platforms,
            "player_perspectives": game_data.get("player_perspectives"),
            "igdb_url": game_data.get("url"),
            "videos": videos,
            "bundles": game_data.get("bundles"),
            "dlcs": game_data.get("dlcs"),
            "expansions": game_data.get("expansions"),
            "ports": game_data.get("ports"),
            "remakes": game_data.get("remakes"),
            "remasters": game_data.get("remasters"),
            "stores": stores,
            "links": links,
        }
        return jsonify(game), 200
    except Exception as e:
        return jsonify({"success": False, "message": f"{e}"}), 500
        
@app.route('/api/sync/stremio', methods=['POST'])
def stremio_sync():
    try:
        auth_header = request.headers.get("authorization", "")
        if not auth_header == f"Bearer {os.environ.get('PASSWORD')}":
            return jsonify({'error': 'Unauthorized'}), 401

        response = requests.post(
            UPSTASH_REDIS_REST_URL,
            headers=headers,
            json=["HGET", "stremio", "ignor_list"]
        )
        ignor_list = json.loads(response.json()['result'])    
        db_data = get_db_data_v2()

        body = {
            "authKey": STREMIO_AUTHKEY,
            "collection": "libraryItem",
            "all": True
        }

        response = requests.post("https://api.strem.io/api/datastoreGet", json=body, headers=stremio_headers)
        data = response.json()
        result = data.get("result") or []

        items_to_consider = [
            item for item in result
                if item.get("_id", "").startswith(("tt", "tmdb"))
                and item.get("type") in ("movie", "series")
                and (
                    not item.get("removed")
                    or (item.get("type") == "series" and bool((item.get("state") or {}).get("watched")))
                )
        ]
        new_items = items_to_consider.copy()
        for item in items_to_consider:
            item_type = "movie" if item.get('type') == "movie" else "tv"
            ignor_list_id = ""
            if item.get('_id').startswith("tmdb:"):
                ignor_list_id = (f"tmdb:{item_type}:{item.get('_id').split(":")[1]}")
            else:
                ignor_list_id = item.get('_id')
            if ignor_list_id in ignor_list:
                new_items.remove(item)

        if new_items:
            for new_item in new_items:
                ignor_list_id = ""
                item_id = ""
                media_type = "movie" if new_item.get('type') == "movie" else "tv"
                if new_item.get('_id').startswith("tmdb:"):
                    ignor_list_id = (f"tmdb:{item_type}:{new_item.get('_id').split(":")[1]}")
                    item_id = new_item.get('_id').split(":")[1]
                else:
                    ignor_list_id = new_item.get("_id")
                    response = requests.get(f"https://api.themoviedb.org/3/find/{new_item.get('_id')}?external_source=imdb_id&api_key={TMDB_API_KEY}")
                    time.sleep(0.1)
                    item_tmdb = response.json() or {}
                    if media_type == "movie":
                        item_tmdb = item_tmdb.get("movie_results")
                    elif media_type == "tv":
                        item_tmdb = item_tmdb.get("tv_results")


                    if item_tmdb:
                        item_tmdb = item_tmdb[0]
                        item_id = item_tmdb.get("id") or ""


                if item_id and ignor_list_id and media_type:
                    print(f"appending {ignor_list_id}")
                    ignor_list.append(ignor_list_id)
                    alrady_in_the_list = False
                    for media in db_data:
                        if media.get("media_type") == media_type and str(media.get("id")) == str(item_id):
                            alrady_in_the_list = True
                            break
                    if not alrady_in_the_list:
                        get_data_for_add_item(item_id, media_type)
                        time.sleep(0.3)
            requests.post(
                UPSTASH_REDIS_REST_URL,
                headers=headers,
                json=["HSET", "stremio", "ignor_list", json.dumps(ignor_list)]
            )
        return jsonify({"success": True, "message": f"successfully sync the data"}), 200
    except Exception as e:
        return jsonify({"success": False, "message": f"{e}"}), 500  

@app.route('/api/calendar/make', methods=['POST'])
def make_calendar():
    
    try:
    
        auth_header = request.headers.get("authorization", "")
        if not auth_header == f"Bearer {os.environ.get('PASSWORD')}":
            return jsonify({'error': 'Unauthorized'}), 401

        db_data = get_db_data_v2()
        calendar = []
        #tv calendar
        tv_calendar = []
        def make_tv_calendar():
            id_list = [item.get("tvmaze_id") for item in db_data if item.get("tvmaze_id")]
            response = requests.get("https://api.tvmaze.com/schedule/full")
            data = response.json()
            for show in data:
                if ((show.get("_embedded") or {}).get("show") or {}).get("id") in id_list:
                    tvmaze_id = ((show.get("_embedded") or {}).get("show") or {}).get("id")
                    db_item = next(item for item in db_data if item.get("tvmaze_id") == tvmaze_id)
                    ep_type = "Regular"
                    max_ep_number = max(e["number"] for e in data if ((e.get("_embedded") or {}).get("show") or {}).get("id") == tvmaze_id and e.get("season") == show.get("season"))
                    if show["number"] == max_ep_number:
                        ep_type = "Season Finale"
                    if show.get("number") == 1:
                        ep_type = "Season Premiere"
                        if show.get("season") == 1:
                            ep_type = "Series Premiere"

                    airstamp = datetime.fromisoformat(show.get("airstamp") or f"{show.get('airdate')}T12:00:00+00:00")
                    if not show.get("airtime"):
                        airstamp = airstamp.replace(hour=7)
                        show_path = show.get("show") or show.get("_embedded", {}).get("show", {})
                        web_channel_obj = show_path.get("webChannel") or show.get("webChannel") or {}
                        web_channel = web_channel_obj.get("name") if isinstance(web_channel_obj, dict) else None
                        if web_channel:
                            if web_channel == "Prime Video":
                                airstamp = airstamp.replace(hour=0)
                            elif web_channel == "Apple TV":
                                airstamp = airstamp.replace(hour=1)
                            elif web_channel == "Disney+":
                                airstamp = (airstamp + timedelta(days=1)).replace(hour=1)
                            elif web_channel == "Hulu":
                                airstamp = airstamp.replace(hour=4)
                            elif web_channel == "Peacock":
                                airstamp = airstamp.replace(hour=9)
                        
                    tv_calendar.append({
                        "id": db_item.get("id"),
                        "tvmaze_id": tvmaze_id,
                        "poster_path": db_item.get("poster_path"),
                        "title": db_item.get("title"),
                        "media_type": "tv",
                        'season': show.get("season"),
                        'number': show.get("number"),
                        'airstamp': airstamp.isoformat(),
                        'runtime': show.get("runtime"),
                        'name': show.get('name'),
                        'url': show.get('url'),
                        'type': ep_type
                    })
                    
        movie_calendar = []
        def make_movie_calendar():
            for item in db_data:
                if item.get("media_type") == "movie" and (item.get("theatrical_release") or item.get("digital_release")):
                    if item.get("theatrical_release"):
                        movie_calendar.append({
                            "id": item.get("id"),
                            "poster_path": item.get("poster_path"),
                            "title": item.get("title"),
                            "media_type": "movie",
                            'airstamp': item.get("theatrical_release"),
                            'runtime': item.get("runtime"),
                            'type': "Theatrical Release",
                        })   
                    if item.get("digital_release"):
                        movie_calendar.append({
                            "id": item.get("id"),
                            "poster_path": item.get("poster_path"),
                            "title": item.get("title"),
                            "media_type": "movie",
                            'airstamp': item.get("digital_release"),
                            'runtime': item.get("runtime"),
                            'type': "Digital Release",
                        })   


        game_calendar = []
        def make_game_calendar():
            game_id_list = [item.get("id") for item in db_data if item.get("media_type") == "game"]
            formatted_ids = ", ".join(map(str, game_id_list))
            fields = (  
                "date_format.format, platform.abbreviation, date, status,"
                "game.name, game.game_type.type, game.involved_companies.developer, game.involved_companies.company.name, game.genres.name, game.cover.image_id,game.platforms.abbreviation,"
                "game.parent_game,game.parent_game.name, game.parent_game.cover.image_id;"
                f"where (game = ({formatted_ids}) | game.parent_game = ({formatted_ids})) & date >= {int(datetime.now(timezone.utc).timestamp())};"
                "sort date asc; "
                "limit 500;"
            )
            response = requests.post(f"https://api.igdb.com/v4/release_dates" ,headers=igdb_headers, data=f'fields {fields}')
            data = response.json()
    
            unique_games = {}
            for entry in data:
                g_id = entry['game']['id']
                if g_id not in unique_games:
                    unique_games[g_id] = entry
    
            final_list = list(unique_games.values())
    
            for game in final_list:
                candidate_ids = [
                    ((game.get("game") or {}).get("parent_game") or {}).get("id"),
                    (game.get("game") or {}).get("id"),
                    game.get("id")
                ]
                matched_db_id = next((candidate_id for candidate_id in candidate_ids if candidate_id in game_id_list), None)
                db_item = next(_ for _ in db_data if _.get("media_type") == "game" and _.get("id") == matched_db_id)
                platforms = [platform.get("abbreviation") for platform in (game.get("game") or {}).get('platforms') or []]
                involved = game.get("game", {}).get("involved_companies") or []
                developer = [item.get("company", {}).get("name", "") for item in involved if item.get("developer")]
                developer = developer[0] if developer else ""
                game_calendar.append({
                    "id": matched_db_id,
                    "title": db_item.get("title"),
                    "poster_path": ((game.get("game") or {}).get('cover') or {}).get('image_id') or db_item.get("poster_path"),
                    "media_type": "game",
                    "type": ((game.get("game") or {}).get('game_type') or {}).get('type') or "",
                    "name": (game.get("game") or {}).get('name') or "",
                    'platforms': platforms,
                    'airstamp': datetime.fromtimestamp(game.get("date"), timezone.utc).isoformat(),
                    "date_format" : (game.get('date_format') or {}).get('format') or "",
                    "alt_id": (game.get("game") or {}).get('id') or "",
                    "developer": developer
                })


        t1 = threading.Thread(target=make_tv_calendar)
        t2 = threading.Thread(target=make_movie_calendar)
        t3 = threading.Thread(target=make_game_calendar)
        
        t1.start()
        t2.start()
        t3.start()
        
        t1.join()
        t2.join()
        t3.join()
        
        calendar =  tv_calendar + movie_calendar + game_calendar

        requests.post(UPSTASH_REDIS_REST_URL, headers=headers, json=["SET", "calendar", json.dumps(calendar)])
        
        return jsonify({"success": True, "message": "calendar created successfully"}), 200
    except Exception as e:
        return jsonify({"success": False, "message": f"{e}"}), 500
        
@app.route('/api/calendar/get', methods=['POST'])
def get_calendar():
    
    auth_header = request.headers.get("authorization", "")
    if not auth_header == f"Bearer {os.environ.get('PASSWORD')}":
        return jsonify({'error': 'Unauthorized'}), 401
    
    response = requests.post(UPSTASH_REDIS_REST_URL, headers=headers, json=["GET", "calendar"])
    result_str = response.json().get('result')
    data = json.loads(result_str) if result_str else []
    return jsonify(data), 200

@app.route('/api/calendar/get/ics.ics', methods=['GET'])
def get_ics():
    response = requests.post(UPSTASH_REDIS_REST_URL, headers=headers, json=["GET", "calendar"])
    result_str = response.json().get('result')
    data = json.loads(result_str) if result_str else []
    
    data = [item for item in data if item.get("airstamp") and datetime.fromisoformat(item.get("airstamp")) >= (datetime.now(timezone.utc) - timedelta(days=3))]
    
    ics_lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//MediaReleaseTracker//EN",
        "X-WR-CALNAME:Media Releases"
    ]
    
    for item in data:
        start_dt = datetime.fromisoformat(item["airstamp"])
        runtime_mins = item.get("runtime") or 60
        end_dt = start_dt + timedelta(minutes=runtime_mins)
        
        start_utc = start_dt.astimezone(timezone.utc)
        end_utc = end_dt.astimezone(timezone.utc)
        
        start_str = start_utc.strftime("%Y%m%dT%H%M%SZ")
        end_str = end_utc.strftime("%Y%m%dT%H%M%SZ")
        
        
        media_type = item.get("media_type")
        item_id = item["id"]
        rel_type = str(item.get('type', 'release')).lower().replace(' ', '_')
        
        if media_type == "tv":
            uid = f"tv-{item_id}-{item['season']}x{item['number']}@media-release-notification.vercel.app"
            ep_name = item.get("name")
            name_str = f" - {ep_name}" if ep_name else ""
            summary = f"📺 {item['title']} {item['season']}x{item['number']:02d}{name_str}"
            desc = f"Type: {item.get('type', 'Episode')}\\nURL: {item.get('url', '')}"
            
        elif media_type == "movie":
            uid = f"movie-{item_id}-{rel_type}@media-release-notification.vercel.app"
            summary = f"🎬 {item['title']} ({item.get('type', 'Movie')})"
            desc = f"Media: Movie\\nType: {item.get('type', 'N/A')}\\nURL: https://www.themoviedb.org/movie/{item_id}"
        
        elif media_type == "game":
            uid = f"game-{item_id}-{rel_type}@media-release-notification.vercel.app"
            game_name = item.get("name") or item["title"]
            summary = f"🎮 {game_name} ({item.get('type', 'Game')})"
            platforms = ", ".join(item.get("platforms", []))
            desc = f"Media: Game\\nType: {item.get('type', 'N/A')}\\nPlatforms: {platforms}"
            
        ics_lines.extend([
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTART:{start_str}",
            f"DTEND:{end_str}",
            f"SUMMARY:{summary}",
            f"DESCRIPTION:{desc}",
            "END:VEVENT"
        ])
        
    ics_lines.append("END:VCALENDAR")
    
    return Response(
        "\r\n".join(ics_lines), 
        mimetype="text/calendar",
        headers={"Content-Disposition": "inline; filename=calendar.ics"}
    )

@app.route('/api/recommendations/make', methods=['POST'])
def make_recommendations():
    try:
        db_data = get_db_data_v2()

        movie_genres_by_id = {
            28: "Action",
            12: "Adventure",
            16: "Animation",
            35: "Comedy",
            80: "Crime",
            99: "Documentary",
            18: "Drama",
            10751: "Family",
            14: "Fantasy",
            36: "History",
            27: "Horror",
            10402: "Music",
            9648: "Mystery",
            10749: "Romance",
            878: "Science Fiction",
            10770: "TV Movie",
            53: "Thriller",
            10752: "War",
            37: "Western"
        }

        tv_genres_by_id = {
            10759: "Action & Adventure",
            16: "Animation",
            35: "Comedy",
            80: "Crime",
            99: "Documentary",
            18: "Drama",
            10751: "Family",
            10762: "Kids",
            9648: "Mystery",
            10763: "News",
            10764: "Reality",
            10765: "Sci-Fi & Fantasy",
            10766: "Soap",
            10767: "Talk",
            10768: "War & Politics",
            37: "Western"
        }

        sorted_db_data = sorted(db_data, key=lambda item: item.get("added_date") or "", reverse=True)
        
        tv_recommendations_finel = []
        def make_tv_recommendations():
            sorce_tv = [item for item in sorted_db_data if item.get("media_type") == "tv"][:15]
            tracked_show_ids = [item.get("id") for item in sorted_db_data if item.get("media_type") == "tv"]
            tv_all_recommendations = []
            tv_all_recommendations_count = {}
    
            for show in sorce_tv:
                response = requests.get(f"https://api.themoviedb.org/3/tv/{show.get("id")}/recommendations?api_key={TMDB_API_KEY}").json()
                data = response.get("results", [])
                for recommendation in data:
                    recommendation_id = recommendation.get("id")
                    if recommendation in tracked_show_ids:
                        continue
                    if not tv_all_recommendations_count.get(recommendation_id):
                        tv_all_recommendations_count[recommendation_id] = 1
                        tv_all_recommendations.append(recommendation)
                    else:
                        tv_all_recommendations_count[recommendation_id] += 1
    
            top_20_recommendation_ids = sorted(
                tv_all_recommendations_count, 
                key=tv_all_recommendations_count.get, 
                reverse=True
            )[:20]
            tv_recommendations = [item for item in tv_all_recommendations if item.get("id") in top_20_recommendation_ids]
            tv_recommendations.sort(key=lambda item: tv_all_recommendations_count.get(item.get("id"), 0), reverse=True)
            for show in tv_recommendations: 
                tv_recommendations_finel.append({
                    "id": show.get("id"),
                    "title": show.get("name"),
                    "poster_path": show.get("poster_path"),
                    "genres": [
                        {
                            "id": genre_id,
                            "name": tv_genres_by_id.get(genre_id)
                        }
                        for genre_id in show.get("genre_ids", [])
                        if genre_id in tv_genres_by_id
                    ],
                    'release_date': show.get("first_air_date", ""),
                    'vote_average': show.get('vote_average', 0),
                    'popularity': show.get('popularity', 0),
                    'recommendation_score': tv_all_recommendations_count.get(show.get("id"), 0),
                    'media_type': "tv"
                })

        movie_recommendations_finel = []
        def make_movie_recommendations():
            sorce_movie = [item for item in sorted_db_data if item.get("media_type") == "movie"][:15]
            tracked_movies_ids = [item.get("id") for item in sorted_db_data if item.get("media_type") == "movie"]
            movie_all_recommendations = []
            movie_all_recommendations_count = {}
            for movie in sorce_movie:
                response = requests.get(f"https://api.themoviedb.org/3/movie/{movie.get("id")}/recommendations?api_key={TMDB_API_KEY}").json()
                data = response.get("results", [])
                for recommendation in data:
                    recommendation_id = recommendation.get("id")
                    if recommendation in tracked_movies_ids:
                        continue

                    if not movie_all_recommendations_count.get(recommendation_id):
                        movie_all_recommendations_count[recommendation_id] = 1
                        movie_all_recommendations.append(recommendation)
                    else:
                        movie_all_recommendations_count[recommendation_id] += 1
            top_20_recommendation_ids = sorted(
                movie_all_recommendations_count, 
                key=movie_all_recommendations_count.get, 
                reverse=True
            )[:20]
            movie_recommendations = [item for item in movie_all_recommendations if item.get("id") in top_20_recommendation_ids]
            movie_recommendations.sort(key=lambda item: movie_all_recommendations_count.get(item.get("id"), 0), reverse=True)
            for movie in movie_recommendations:
                movie_recommendations_finel.append({
                        "id": movie.get("id"),
                        "title": movie.get("title"),
                        "poster_path": movie.get("poster_path"),
                        "genres": [
                            {
                                "id": genre_id,
                                "name": movie_genres_by_id.get(genre_id)
                            }
                            for genre_id in movie.get("genre_ids", [])
                            if genre_id in movie_genres_by_id
                        ],
                        'release_date': movie.get("release_date", ""),
                        'vote_average': movie.get('vote_average', 0),
                        'popularity': movie.get('popularity', 0),
                        'recommendation_score': movie_all_recommendations_count.get(movie.get("id"), 0) + 2,
                        'media_type': "movie"
                    })


        game_recommendations_finel = []
        def make_game_recommendations():
            sorce_game = [item for item in sorted_db_data if item.get("media_type") == "game"][:15]
            tracked_games_ids = [item.get("id") for item in sorted_db_data if item.get("media_type") == "game"]
            tracked_game_ids_string = ", ".join(str(game.get("id")) for game in sorce_game)
            fields = "name, similar_games.id, similar_games.name, similar_games.cover.image_id, similar_games.rating,  similar_games.genres.name, similar_games.first_release_date,  similar_games.hypes"
            filters = f"id = ({tracked_game_ids_string})"
            response = requests.post("https://api.igdb.com/v4/games", headers=igdb_headers, data=f"fields {fields}; where {filters}; limit 50;").json()
            game_recommendations_raw = [item.get('similar_games') for item in response]
            game_all_recommendations = []
            game_all_recommendations_count = {}

            for recommendations in game_recommendations_raw:
                for recommendation in recommendations:
                    recommendation_id = recommendation.get("id")
                    if recommendation in tracked_games_ids:
                        continue
                    
                    if not game_all_recommendations_count.get(recommendation_id):
                        game_all_recommendations_count[recommendation_id] = 1
                        game_all_recommendations.append(recommendation)
                    else: 
                        game_all_recommendations_count[recommendation_id] += 1

            top_20_recommendation_ids = sorted(
                game_all_recommendations_count, 
                key=game_all_recommendations_count.get, 
                reverse=True
            )[:20]
            game_recommendations = [item for item in game_all_recommendations if item.get("id") in top_20_recommendation_ids]
            game_recommendations.sort(key=lambda item: game_all_recommendations_count.get(item.get("id"), 0), reverse=True)

            for game in game_recommendations:
                release_date = datetime.fromtimestamp(game.get("first_release_date", 0) or 0, timezone.utc)
                game_recommendations_finel.append({
                    "id": game.get("id"),
                    "title": game.get("name"),
                    "poster_path": (game.get("cover") or {}).get('image_id', ""),
                    "genres": game.get('genres', []),
                    'release_date': release_date.date().isoformat(),
                    'vote_average': game.get("rating"),
                    'popularity': game.get("hypes", 0) or 0,
                    'recommendation_score': game_all_recommendations_count.get(game.get("id"), 0) - 1,
                    'media_type': "game"
                })

        t1 = threading.Thread(target=make_tv_recommendations)
        t2 = threading.Thread(target=make_movie_recommendations)
        t3 = threading.Thread(target=make_game_recommendations)
        
        t1.start()
        t2.start()
        t3.start()

        t1.join()
        t2.join()
        t3.join()


        recommendations_finel: list = tv_recommendations_finel + movie_recommendations_finel + game_recommendations_finel
        recommendations_finel = sorted(recommendations_finel, key=lambda item : item.get("recommendation_score"), reverse=True)
        requests.post(UPSTASH_REDIS_REST_URL, headers=headers, json=["SET", "Recommendations", json.dumps(recommendations_finel)])
        return jsonify({"success": True, "message": "recommendations created successfully"}), 200
    except Exception as e:
        return jsonify({"success": False, "message": f"{e}"}), 500

@app.route('/api/recommendations/get', methods=['POST'])
def get_recommendations():
    
    auth_header = request.headers.get("authorization", "")
    if not auth_header == f"Bearer {os.environ.get('PASSWORD')}":
        return jsonify({'error': 'Unauthorized'}), 401
    
    response = requests.post(UPSTASH_REDIS_REST_URL, headers=headers, json=["GET", "Recommendations"])
    result_str = response.json().get('result')
    data = json.loads(result_str) if result_str else []
    return jsonify(data), 200

@app.route('/api/manifest.json', methods=['GET'])
def manifest():
    return jsonify({

        "id": "com.erez225.mypersonaltmdblist", 
        "version": "1.0.0", 
        "name": "My Personal TMDB Catalog", 
        "description": "Personal movie and series list served from Vercel serverless function",
        "resources": ["catalog"],
        "types": ["movie", "series"],
        "idPrefixes": ["tt", "tmdb"],
        
        "catalogs": [
            {
                "id": "my_custom_catalog",
                "type": "movie",
                "name": "My Favorites: Movies",
                "extra": [
                    {
                      "name": "genre",
                      "isRequired": False,
                      "options": ["Sort: Dynamic", "Sort: Latest", "Sort: Newest First",  "Sort: Oldest First", "Sort: Release Date Newest First", "Sort: Release Date Oldest First", "Sort: Popularity Highest First", "Sort: Popularity Lowest First", "Sort: Alphabetical", "Availble on Digital", "Not Availble on Digital", "Action", "Adventure", "Animation", "Comedy", "Crime", "Documentary", "Drama", "Family", "Fantasy", "History", "Horror", "Music", "Mystery", "Romance", "Science Fiction", "TV Movie", "Thriller", "War", "Western"]
                    }
                ]
            },
            {
                "id": "my_custom_catalog",
                "type": "series",
                "name": "My Favorites: TV Shows",
                "extra": [
                    {
                      "name": "genre",
                      "isRequired": False,
                      "options": ["Sort: Dynamic", "Sort: Latest", "Sort: Newest First",  "Sort: Oldest First", "Sort: First Air Date Newest First", "Sort: First Air Date Oldest First", "Sort: Last Air Date Newest First", "Sort: Last Air Date Oldest First", "Sort: Popularity Highest First", "Sort: Popularity Lowest First", "Sort: Alphabetical", "Action & Adventure", "Animation", "Comedy", "Crime", "Documentary", "Drama", "Family", "Kids", "Mystery", "News", "Reality", "Sci-Fi & Fantasy", "Soap", "Talk", "War & Politics", "Western"]
                    }
                ]
            }
        ]
    })
    
@app.route('/api/catalog/<string:content_type>/<path:catalog_id_path>', methods=['GET'])
def catalog(content_type, catalog_id_path):
    try:
        
        clean_path = urllib.parse.unquote(catalog_id_path.replace(".json", ""))
        
        catalog_id = clean_path
        selected_option = "Sort: Dynamic"
        
        if "/" in clean_path:
            catalog_id, args_string = clean_path.split("/", 1)
        
            parsed_args = urllib.parse.parse_qs(args_string)
            if "genre" in parsed_args:
                selected_option = parsed_args["genre"][0]
        
        if catalog_id == "my_custom_catalog":
            db_data = get_db_data_v2()


            if selected_option == "Sort: Newest First":
                db_data = sorted(db_data, key=lambda item: item.get("added_date", "") or "", reverse=True)
            elif selected_option == "Sort: Oldest First":
                db_data = sorted(db_data, key=lambda item: item.get("added_date", "") or "", reverse=False)
            elif selected_option == "Sort: Alphabetical":
                db_data = sorted(db_data, key=lambda item: item.get("title").lower() or "")
            elif selected_option == "Sort: Release Date Newest First":
                db_data = sorted(db_data, key=lambda item: item.get("release_date", "") or "", reverse=True)
            elif selected_option == "Sort: Release Date Oldest First":
                db_data = sorted(db_data, key=lambda item: item.get("release_date", "") or "")
            elif selected_option == "Sort: First Air Date Newest First":
                db_data = sorted(db_data, key=lambda item: item.get("first_air_date", "") or "", reverse=True)
            elif selected_option == "Sort: First Air Date Oldest First":
                db_data = sorted(db_data, key=lambda item: item.get("first_air_date", "") or "")
            elif selected_option == "Sort: Last Air Date Newest First":
                db_data = sorted(db_data, key=lambda item: item.get("last_air_date") or "30000-01-01", reverse=True)
            elif selected_option == "Sort: Last Air Date Oldest First":
                db_data = sorted(db_data, key=lambda item: item.get("last_air_date") or "30000-01-01")
            elif selected_option == "Sort: Popularity Highest First":
                db_data = sorted(db_data, key=lambda item: item.get("popularity") or 0, reverse=True)
            elif selected_option == "Sort: Popularity Lowest First":
                db_data = sorted(db_data, key=lambda item: item.get("popularity") or 0)
            elif selected_option == "Availble on Digital":
                db_data = [item for item in db_data if item.get("digital", "")]
            elif selected_option == "Not Availble on Digital":
                db_data = [item for item in db_data if not item.get("digital", "")]
            elif selected_option == "Sort: Latest":
                db_data = sorted(
                    db_data, 
                    key=lambda item: (
                        item.get("last_air_date") if item.get("media_type") == "tv" 
                        else (item.get("digital_release") or item.get("release_date") if item.get("digital") else "")
                    ) or "", 
                    reverse=True
                )
            elif selected_option == "Sort: Dynamic":
                now = datetime.now().date()
                w_start = (now - timedelta(days=3)).isoformat()
                w_end = (now + timedelta(days=3)).isoformat()
                
                db_data = sorted(
                    db_data,
                    key=lambda i: (
                        # Group 0: In ±3 day window comes first. Group 1: Fallback.
                        0 if any(w_start <= d.split("T")[0] <= w_end for d in [
                            i.get("next_air_date"), 
                            i.get("last_air_date"), 
                            i.get("digital_release") if i.get("digital") else None, 
                            i.get("release_date")
                        ] if d) else 1,

                        # Sub-sort for window items (chronological order, ascending)
                        next((d.split("T")[0] for d in [
                            i.get("next_air_date"), 
                            i.get("last_air_date"), 
                            i.get("digital_release") if i.get("digital") else None, 
                            i.get("release_date")
                        ] if d and w_start <= d.split("T")[0] <= w_end), ""),

                        # Fallback sub-sort: newest added_date first (descending via negative ordinal)
                        -datetime.strptime((i.get("added_date") or "1970-01-01").split("T")[0], "%Y-%m-%d").toordinal()
                    )
                )
                

            else:
                filtered_data = []
                for item in db_data:
                    item_genres = item.get("genres", [])
                    genre_names = [g.get("name") for g in item_genres if g.get("name")]
                    if selected_option in genre_names:
                        filtered_data.append(item)
                db_data = filtered_data
                db_data = sorted(db_data, key=lambda item : item.get("added_date", ""), reverse=True)



            if content_type == "movie":
                movies = []
                for movie in db_data:
                    if movie.get("media_type") == "movie":
                        poster_path = movie.get("poster_path")
                        movies.append({
                            "id": movie.get("imdb_id") if movie.get("imdb_id") else f"tmdb:{movie.get('id')}", 
                            "type": "movie",
                            "name": f"{movie['title']}",
                            "poster": f"https://image.tmdb.org/t/p/w342{poster_path}" if poster_path else "https://placehold.co"
                            }) 
                return jsonify({"metas": movies})
            if content_type == "series":
                shows = []
                for show in db_data:
                    poster_path = show.get("poster_path")
                    if show["media_type"] == "tv":
                        item_id = show.get("imdb_id") if show.get("imdb_id") else f"tmdb:{show.get('id')}"
                        shows.append({
                            "id": item_id,
                            "type": "series",
                            "name": f"{show.get('title') or show.get('name', 'Unknown')}",
                            "poster": f"https://image.tmdb.org/t/p/w342{poster_path}" if poster_path else "https://placehold.co"
                        })
                return jsonify({"metas": shows})

        return jsonify({"metas": []}), 404
    except Exception as e:
        return jsonify({"success": False, "message": f"{e}"}), 500

@app.route('/api/checker/subs', methods=['POST'])
def seb_check():
    try:
        auth_header = request.headers.get("authorization", "")
        if not auth_header == f"Bearer {os.environ.get('PASSWORD')}":
            return jsonify({'error': 'Unauthorized'}), 401

        open_sub_headers = {
            "Content-Type": "application/json",
            "Api-Key": os.environ.get('OPENSUBTITLES_AUTHKEY'),
            "User-Agent": "erezTest v1.0.0"
        }
        response = requests.post(
            UPSTASH_REDIS_REST_URL,
            headers=headers,
            json=["HVALS", "heb-subs-list"]
        )


        raw_list = response.json()["result"]

        sub_list = [json.loads(item) for item in raw_list if item.startswith('{')]


        if sub_list:
            for item in sub_list:
                if not item.get("last_checked") or datetime.fromisoformat(item.get("last_checked")).date() != datetime.now(timezone.utc).date():
                    id = item.get("id") or ""
                    season = item.get("season") or 0
                    episode = item.get("episode") or 0
                    have_sub = False
                    item["last_checked"] = datetime.now(timezone.utc).isoformat()
                    if id and season and episode:
                        response = requests.get(f"https://api.opensubtitles.com/api/v1/subtitles?parent_imdb_id={id}&languages=he", headers=open_sub_headers)
                        print(response)
                        if response.status_code == 200:
                            open_data = response.json()
                            if open_data:
                                open_data = open_data.get("data")
                                if open_data:
                                    for sub in open_data:
                                        if ((sub.get('attributes') or {}).get('feature_details') or {}).get("season_number") == season and ((sub.get('attributes') or {}).get('feature_details') or {}).get("episode_number") == episode:
                                            have_sub = True
                                            break
                    if not have_sub:
                        url = f"https://4b139a4b7f94-ktuvit-stremio.baby-beamup.club/subtitles/series/{id}:{season}:{episode}/videoHash=&videoSize=.json"

                        response = requests.get(url)
                        if response.status_code == 200:
                            data = response.json()
                            if data:
                                if (data.get('subtitles')or {}):
                                    have_sub = True

                    field = f"{item.get("movie_type")}:{id}:{season}:{episode}"
                    if have_sub:
                        requests.post(F"https://ntfy.sh/{NTFY_SUB_CHANNEL}", data=f"כתוביות ל-{item.get("name")} עונה: {season} פרק: {episode} יצאו")
                        requests.post(
                            UPSTASH_REDIS_REST_URL,
                                headers=headers,
                                json=["HDEL", "heb-subs-list", field]
                        )

                        break
                    requests.post(
                        UPSTASH_REDIS_REST_URL,
                        headers=headers,
                        json=["HSET", "heb-subs-list", field, json.dumps(item)]
                    )
                    break
                
        return jsonify({"success": True, "message": f"successfully cheaked for subs"}), 200
    
    except Exception as e:
        return jsonify({"success": False, "message": f"{e}"}), 500




# def game_checker_old():
    
#     auth_header = request.headers.get("authorization", "")
#     if not auth_header == f"Bearer {os.environ.get('PASSWORD')}":
#         return jsonify({'error': 'Unauthorized'}), 401
    
#     watchlist = get_db_data_v2()
    
#     limit = 18
#     items_before_sleeping = 3
#     sleep_for = 2
    
#     count = 0

#     for item in watchlist:
        
#         if count == limit:
#             break
#         try:
#             if item.get("media_type") == "game" and (not item.get("last_checked") or datetime.fromisoformat(item.get("last_checked")).date() != datetime.now(timezone.utc).date()):

#                 # checking if we need to wait a bit before the next req
#                 if count and count % items_before_sleeping == 0:
#                     time.sleep(sleep_for)


#                 fields = (
#                     "name,cover.image_id,first_release_date,game_type,game_status,genres.name,hypes,summary,rating,rating_count,"
#                     "involved_companies.company.name,involved_companies.developer,involved_companies.publisher,"
#                     "platforms.abbreviation,"
#                     "release_dates.status.name,release_dates.date,"
#                     "dlcs.name,dlcs.first_release_date,dlcs.game_type.type,dlcs.cover.image_id,"
#                     "expanded_games.name,expanded_games.first_release_date,expanded_games.game_type.type,expanded_games.cover.image_id,"
#                     "expansions.name,expansions.first_release_date,expansions.game_type.type,expansions.cover.image_id,"
#                     "ports.name,ports.first_release_date,ports.game_type.type,ports.cover.image_id,"
#                     "remakes.name,remakes.first_release_date,remakes.game_type.type,remakes.cover.image_id,"
#                     "remasters.name,remasters.first_release_date,remasters.game_type.type,remasters.cover.image_id,"
#                     "standalone_expansions.name,standalone_expansions.first_release_date,standalone_expansions.game_type.type,standalone_expansions.cover.image_id"
#                 )
#                 response = requests.post(f"https://api.igdb.com/v4/games" ,headers=igdb_headers, data=f'fields {fields}; where id = {item["id"]};')
#                 count += 1
#                 data = response.json()
#                 if not data:
#                     continue
#                 game = data[0]
#                 item["last_checked"] = datetime.now(timezone.utc).isoformat()

#                 item_timestamp_raw = game.get("first_release_date")
#                 item_release_date = ""
#                 if item_timestamp_raw is not None:
#                     item_original_release_date = float(item_timestamp_raw)
#                     item_release_date = datetime.fromtimestamp(item_original_release_date, timezone.utc).date().isoformat()

#                 item["title"] = game.get("name") or ""
#                 item["poster_path"] = (game.get("cover") or {}).get("image_id") or ""
#                 item["overview"] = game.get("summary") or ""
#                 item["genres"] = game.get("genres") or []
#                 item["release_date"] = item_release_date
#                 item["popularity"] = game.get("hypes") or 0
#                 item["vote_average"] = game.get("rating") or 0
#                 item["vote_count"] = game.get("rating_count") or 0
                

#                 # chaking 


#                 # **checking main game**

#                 #checking for shod droop
#                 if not item.get("released") and not item.get("notification_soon"):
#                     if game.get("first_release_date") and datetime.fromtimestamp(game.get("first_release_date"), timezone.utc).date() <= datetime.now(timezone.utc).date():
#                         body = {
#                                 "id": game.get("id"),
#                                 "media_type": "game",
#                                 "title": game.get("name", ""), 
#                                 "overview": game.get("summary", ""),
#                                 "poster_path": game.get("cover", {}).get("image_id"),
#                                 "genres": game.get("genres", []),
#                                 "involved_companies": game.get("involved_companies", []),
#                                 "platforms": game.get("platforms", []),
#                                 'release_date': game.get("first_release_date")
#                             }
#                         item["released"] = True
#                         send_game_to_qstush(0, body)
#                         update_one_item_in_db(item)
#                         continue

#                     #checking for tomorrow dates
#                     release_dates = game.get("release_dates") or []

#                     upcoming_main_game_dates = []
#                     for date in release_dates:
#                         if date.get("date") and datetime.fromtimestamp(date.get("date"), timezone.utc).date() == datetime.now(timezone.utc).date() + timedelta(days=1):
#                             upcoming_main_game_dates.append({"date": date['date'], "status": (date.get("status") or {}).get("name", "")})

#                     if upcoming_main_game_dates:
#                         body = {
#                            "id": game.get("id"),
#                            "media_type": "game",
#                            "title": game.get("name", ""), 
#                            "overview": game.get("summary", ""),
#                            "poster_path": game.get("cover", {}).get("image_id"),
#                            "genres": game.get("genres", []),
#                            "involved_companies": game.get("involved_companies", []),
#                            "platforms": game.get("platforms", []),
#                            'release_dates': upcoming_main_game_dates
#                         }
#                         time_in_sec = max(0, int(upcoming_main_game_dates[0]["date"] - datetime.now(timezone.utc).timestamp()))
#                         item["notification_soon"] = True
#                         send_game_to_qstush(time_in_sec, body)
#                         update_one_item_in_db(item)
#                         continue
                    
                    
#                 # **side content*
#                 all_content = []
#                 content_fields = [
#                     "dlcs", 
#                     "expanded_games", 
#                     "expansions", 
#                     "remakes", 
#                     "remasters", 
#                     "standalone_expansions",
#                     "ports"
#                 ]
#                 for field in content_fields:
#                     items = game.get(field)
#                     if items:
#                         all_content.extend(items)



#                 # getting shadow drop
#                 missed_content = []
#                 raw_date = item.get("notifications_enabled_at")
#                 notifications_enabled_at = datetime.fromisoformat(raw_date) if raw_date else datetime.now(timezone.utc)
#                 if notifications_enabled_at.tzinfo is None:
#                     notifications_enabled_at = notifications_enabled_at.replace(tzinfo=timezone.utc)
#                 for dlc in all_content:
#                     dlc_id = dlc.get("id")
#                     try:
#                         dlc_release = datetime.fromtimestamp(dlc.get("first_release_date"), timezone.utc)
#                     except TypeError:
#                         dlc_release = False
#                     if dlc_release and  dlc_release >= notifications_enabled_at and not dlc_release > datetime.now(timezone.utc):
#                         if dlc_id and dlc_id not in item.get("notified_content_ids", []):
#                             missed_content.append(dlc)

#                 if missed_content:
#                     body = {
#                         "id": game.get("id"),
#                         "media_type": "game",
#                         "title": game.get("name", ""),
#                         "overview": game.get("summary", ""),
#                         "poster_path": (game.get("cover") or {}).get("image_id"),
#                         "genres": game.get("genres", []),
#                         "involved_companies": game.get("involved_companies", []),
#                         "platforms": game.get("platforms", []),
#                         "content": missed_content
#                     }
#                     notified_ids = item.setdefault("notified_content_ids", [])
#                     notified_ids.extend([dlc["id"] for dlc in missed_content if dlc.get("id")])
#                     send_game_to_qstush(0, body)
#                     update_one_item_in_db(item)
#                     continue
                
#                 # side content tomorrow
#                 upcoming_side_dates = []
#                 for dlc in all_content:
#                     dlc_id = dlc.get("id")
#                     try:
#                         dlc_release = datetime.fromtimestamp(dlc.get("first_release_date"), timezone.utc)
#                     except TypeError:
#                         dlc_release = False
#                     if dlc_release and dlc_release.date() == datetime.now(timezone.utc).date() + timedelta(days=1):
#                         if dlc_id and dlc_id not in item.get("notified_content_ids", []):
#                             upcoming_side_dates.append(dlc)

#                 if upcoming_side_dates:
#                     body = {
#                         "id": game.get("id"),
#                         "media_type": "game",
#                         "title": game.get("name", ""),
#                         "overview": game.get("summary", ""),
#                         "poster_path": (game.get("cover") or {}).get("image_id"),
#                         "genres": game.get("genres", []),
#                         "involved_companies": game.get("involved_companies", []),
#                         "platforms": game.get("platforms", []),
#                         "content": upcoming_side_dates
#                     }
#                     notified_ids = item.setdefault("notified_content_ids", [])
#                     notified_ids.extend([dlc["id"] for dlc in upcoming_side_dates if dlc.get("id")])
#                     if upcoming_side_dates[0].get("first_release_date"):
#                         time_in_sec = max(0, int(upcoming_side_dates[0]["first_release_date"] - datetime.now(timezone.utc).timestamp()))
#                     else:
#                         time_in_sec = 0
#                     send_game_to_qstush(time_in_sec, body)
                    
#                 update_one_item_in_db(item)
#         except Exception as e:
#             continue
#     return jsonify({"success": "true", "message": "check_game checked successfully"}), 200
