from math import e
import os
import time
import json
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from datetime import date, datetime, timezone, timedelta
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

    
def send_to_qstush_movie(seconds_left, body):
    
    target_url = "https://media-release-notification.vercel.app/api/notification/movie"
    qstash_task_header= {
        "Authorization": f"Bearer {QSTASH_TOKEN}",
        "Content-Type": "application/json",
        "Upstash-Delay": f"{seconds_left}s",
        "Upstash-Forward-Authorization": f"Bearer {os.environ.get('PASSWORD')}"
    }
    qstash_publish_endpoint = f"{QSTASH_URL}/publish/{target_url}"
    qstash_task_payload = body
    
    requests.post(qstash_publish_endpoint, headers=qstash_task_header, json=qstash_task_payload)

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

def get_data_for_add_item(media_id, media_type):

        movie_response = requests.get(f"https://api.themoviedb.org/3/{media_type}/{media_id}?api_key={TMDB_API_KEY}")
        digital = check_if_digital(media_id)
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
            "imdb_id": movie_data.get("imdb_id") or None,
            "tvdb_id": None,
            "notifications": True,
            "notifications_enabled_at": datetime.now(timezone.utc).isoformat()
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
        

        game_results = get_game_results(movie_name)
        
        if not (movie_results or tv_results or game_results):
            return jsonify({"error": "No results"}), 404
        
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
def check_movie():
    
    auth_header = request.headers.get("authorization", "")
    if not auth_header == f"Bearer {os.environ.get('PASSWORD')}":
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        limit = 20
        db_data = get_db_data_v2()
        for item in db_data:
            if limit and not item.get("notification_soon", "") and item.get("media_type") == "movie" and not item.get("digital") and (not item.get("last_checked") or datetime.fromisoformat(item.get("last_checked")).date() != datetime.now(timezone.utc).date()):
                
                response = requests.get(f"https://api.themoviedb.org/3/movie/{item['id']}/release_dates?api_key={TMDB_API_KEY}")
                data = response.json()
                
                limit -= 1
                item["last_checked"] = datetime.now(timezone.utc).isoformat()
                
                results = data.get('results' , [])
                
                if not results:
                    continue
                
                tomorrow = datetime.now(timezone.utc).date() + timedelta(days=1)
                movie_notification_now = False
                sec_until_notification = 0
                for country in results:
                    if country.get('release_dates', []):
                        for dates in country['release_dates']:
                            if dates['type'] >= 4 and datetime.fromisoformat(dates['release_date']).date() <= datetime.now(timezone.utc).date():
                                movie_notification_now = dates['release_date']                            
                            elif dates['type'] >= 4 and datetime.fromisoformat(dates['release_date']).date() == tomorrow:
                                target_time = datetime.fromisoformat(dates['release_date'])
                                now = datetime.now(timezone.utc)
                                time_remaining = target_time - now
                                seconds_left = int(time_remaining.total_seconds())
                                sec_until_notification = seconds_left
                
                
                
                if sec_until_notification:
                    item["notification_soon"] = True
                    body = {
                                'daley': sec_until_notification,
                                'show_info': item
                            } 
                    send_to_qstush_movie(sec_until_notification, body)
                if movie_notification_now:
                        item['digital'] = True
                        if item.get("notifications"):
                            send_movie_notification(item, dates['release_date'])
                    
                    
        update_db(db_data)
        return jsonify({"success": "true", "message": "check_movie checked successfully"}), 200
    except Exception as e:
        return jsonify({"error": "Bad Gateway", "message": f"Server error: {e}"}), 502
        
        
@app.route('/api/notification/tv', methods=['POST'])
def send_tv_notification():
    auth_header = request.headers.get("authorization", "")
    if not auth_header == f"Bearer {os.environ.get('PASSWORD')}":
        return jsonify({'error': 'Unauthorized'}), 401

    body = request.get_json() or {}

    
    if len(body) == 1:
        
        episode = body[0]
        show_id = episode.get("id")
        item = get_item_data_from_db({'id': show_id, "media_type": "tv"})
        
        what_new = "Episode"
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
    what_new = "Episodes"
    if first_ep.get("episode") == 1:
        what_new = "Season"
        if first_ep.get("season") == 1:
            what_new = "Show"
            
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
def check_tv():
    try:
        auth_header = request.headers.get("authorization", "")
        if not auth_header == f"Bearer {os.environ.get('PASSWORD')}":
            return jsonify({'error': 'Unauthorized'}), 401




        db_data = get_db_data_v2()
        new_episodes_all = []
        request_tvmaze = 10
        for show in db_data:
            if show.get("media_type") == "tv" and show.get("tvmaze_id") and show.get("status") != "Ended" and (not show.get("last_checked") or datetime.fromisoformat(show.get("last_checked")).date() < datetime.now(timezone.utc).date()):

                if not request_tvmaze:
                    break
                
                response = requests.get(f"https://api.tvmaze.com/shows/{show.get('tvmaze_id')}/episodes")
                show["last_checked"] = datetime.now(timezone.utc).isoformat()
                request_tvmaze -= 1
                tvmaze_data = response.json() or {}
                new_episodes = []
                for ep in tvmaze_data:
                    if  datetime.fromisoformat(ep.get("airstamp")).astimezone(timezone.utc).date() == (datetime.now(timezone.utc).date() + timedelta(days=1)):
                        new_episodes.append({'id': show.get('id'), 'show_name': show.get('title'), 'season': ep.get('season'), 'episode': ep.get('number'), 'airstamp': ep.get("airstamp"), 'airtime': ep.get('airtime'), 'type': ep.get("type", ""), 'name': ep.get("name", ""), 'poster_path': show.get("poster_path", "")})
                if new_episodes:        
                    new_episodes_all.append(new_episodes)
        update_db(db_data)

        new_episodes_summery_all = []
        for show in new_episodes_all:
            grouped_by_date = {}
            for ep in show:
                date = ep["airstamp"]
                if not date in grouped_by_date:
                    grouped_by_date[date] = []
                grouped_by_date[date].append(ep)
                show_summary = []
                for date, eps in grouped_by_date.items():
                    show_summary.append({
                        "airstamp": date,
                        "episodes": eps
                    })
            new_episodes_summery_all.append(show_summary)

        target_url = "https://media-release-notification.vercel.app/api/notification/tv"
        for show in new_episodes_summery_all:
            for timesteps in show:
                target_time = datetime.fromisoformat(timesteps["airstamp"])
                now = datetime.now(timezone.utc)
                time_remaining = target_time - now
                seconds_left = int(time_remaining.total_seconds())
                qstash_task_header= {
                    "Authorization": f"Bearer {QSTASH_TOKEN}",
                    "Content-Type": "application/json",
                    "Upstash-Delay": f"{seconds_left}s",
                    "Upstash-Forward-Authorization": f"Bearer {os.environ.get('PASSWORD')}"
                }
                qstash_publish_endpoint = f"{QSTASH_URL}/publish/{target_url}"
                qstash_task_payload = timesteps["episodes"]
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
    for item in db_data:
        if not limit:
            break
        
        
        if ((not item.get('last_updated')) or datetime.fromisoformat(item.get('last_updated')).date() != datetime.now(timezone.utc).date()) and item.get('media_type', "") != "game":
            
            response = requests.get(f"https://api.themoviedb.org/3/{item['media_type']}/{item['id']}?api_key={TMDB_API_KEY}")
            data = response.json()
            limit -= 1
            if item.get('media_type', "") == "movie":
                if item.get('title', "") !=  data.get('title', ""):
                    item['title'] = data.get('title', "")
    
            else:
                if item.get('title', "") !=  data.get('name', ""):
                    item['title'] = data.get('name', "")
      
                
            if item.get('poster_path', "") !=  data.get('poster_path', ""):
                item['poster_path'] = data.get('poster_path', "")

                
            if item.get('overview', "") !=  data.get('overview', ""):
                item['overview'] = data.get('overview', "")


            if item.get('runtime', "") !=  data.get('runtime', ""):
                item['runtime'] = data.get('runtime', "")

                
            if item.get('status', "") !=  data.get('status', ""):
                item['status'] = data.get('status', "")

                
            if item.get('genres', "") !=  data.get('genres', ""):
                item['genres'] = data.get('genres', "")

                
            if item.get('release_date', "") !=  data.get('release_date', ""):
                item['release_date'] = data.get('release_date', "")

                
                
            if item.get('first_air_date', "") !=  data.get('first_air_date', ""):
                item['first_air_date'] = data.get('first_air_date', "")

                
            if item.get('last_air_date', "") !=  data.get('last_air_date', ""):
                item['last_air_date'] = data.get('last_air_date', "")

            if data.get('imdb_id') and item.get('imdb_id', "") !=  data.get('imdb_id', ""):
                item['imdb_id'] = data.get('imdb_id', "")
                
            item['last_updated'] = datetime.now(timezone.utc).isoformat()
                
            
    
    update_db(db_data)
    return jsonify({"success": "true", "message": "Updated the media"}), 200


@app.route('/api/checker/game', methods=['POST'])
def game_checker():
    
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
        try:
            if item.get("media_type") == "game" and (not item.get("last_checked") or datetime.fromisoformat(item.get("last_checked")).date() != datetime.now(timezone.utc).date()):

                # checking if we need to wait a bit before the next req
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
                item["last_checked"] = datetime.now(timezone.utc).isoformat()
                #TODO update the item data with the new game data
                
                item_timestamp_raw = game.get("first_release_date")
                item_release_date = ""
                if item_timestamp_raw is not None:
                    item_original_release_date = float(item_timestamp_raw)
                    item_release_date = datetime.fromtimestamp(item_original_release_date, timezone.utc).date().isoformat()

                item["title"] = game.get("name") or ""
                item["poster_path"] = (game.get("cover") or {}).get("image_id") or ""
                item["overview"] = game.get("summary") or ""
                item["genres"] = game.get("genres") or []
                item["release_date"] = item_release_date
                item["popularity"] = game.get("hypes") or 0
                item["vote_average"] = game.get("rating") or 0
                item["vote_count"] = game.get("rating_count") or 0
                

                # chaking 


                # **checking main game**

                #checking for shod droop
                if not item.get("released") and not item.get("notification_soon"):
                    if game.get("first_release_date") and datetime.fromtimestamp(game.get("first_release_date"), timezone.utc).date() <= datetime.now(timezone.utc).date():
                        body = {
                                "id": game.get("id"),
                                "media_type": "game",
                                "title": game.get("name", ""), 
                                "overview": game.get("summary", ""),
                                "poster_path": game.get("cover", {}).get("image_id"),
                                "genres": game.get("genres", []),
                                "involved_companies": game.get("involved_companies", []),
                                "platforms": game.get("platforms", []),
                                'release_date': game.get("first_release_date")
                            }
                        item["released"] = True
                        send_game_to_qstush(0, body)
                        update_one_item_in_db(item)
                        continue

                    #checking for tomorrow dates
                    release_dates = game.get("release_dates") or []

                    upcoming_main_game_dates = []
                    for date in release_dates:
                        if date.get("date") and datetime.fromtimestamp(date.get("date"), timezone.utc).date() == datetime.now(timezone.utc).date() + timedelta(days=1):
                            upcoming_main_game_dates.append({"date": date['date'], "status": (date.get("status") or {}).get("name", "")})

                    if upcoming_main_game_dates:
                        body = {
                           "id": game.get("id"),
                           "media_type": "game",
                           "title": game.get("name", ""), 
                           "overview": game.get("summary", ""),
                           "poster_path": game.get("cover", {}).get("image_id"),
                           "genres": game.get("genres", []),
                           "involved_companies": game.get("involved_companies", []),
                           "platforms": game.get("platforms", []),
                           'release_dates': upcoming_main_game_dates
                        }
                        time_in_sec = max(0, int(upcoming_main_game_dates[0]["date"] - datetime.now(timezone.utc).timestamp()))
                        item["notification_soon"] = True
                        send_game_to_qstush(time_in_sec, body)
                        update_one_item_in_db(item)
                        continue
                    
                    
                # **side content*
                all_content = []
                content_fields = [
                    "dlcs", 
                    "expanded_games", 
                    "expansions", 
                    "remakes", 
                    "remasters", 
                    "standalone_expansions",
                    "ports"
                ]
                for field in content_fields:
                    items = game.get(field)
                    if items:
                        all_content.extend(items)



                # getting shadow drop
                missed_content = []
                raw_date = item.get("notifications_enabled_at")
                notifications_enabled_at = datetime.fromisoformat(raw_date) if raw_date else datetime.now(timezone.utc)
                if notifications_enabled_at.tzinfo is None:
                    notifications_enabled_at = notifications_enabled_at.replace(tzinfo=timezone.utc)
                for dlc in all_content:
                    dlc_id = dlc.get("id")
                    try:
                        dlc_release = datetime.fromtimestamp(dlc.get("first_release_date"), timezone.utc)
                    except TypeError:
                        dlc_release = False
                    if dlc_release and  dlc_release >= notifications_enabled_at and not dlc_release > datetime.now(timezone.utc):
                        if dlc_id and dlc_id not in item.get("notified_content_ids", []):
                            missed_content.append(dlc)

                if missed_content:
                    body = {
                        "id": game.get("id"),
                        "media_type": "game",
                        "title": game.get("name", ""),
                        "overview": game.get("summary", ""),
                        "poster_path": (game.get("cover") or {}).get("image_id"),
                        "genres": game.get("genres", []),
                        "involved_companies": game.get("involved_companies", []),
                        "platforms": game.get("platforms", []),
                        "content": missed_content
                    }
                    notified_ids = item.setdefault("notified_content_ids", [])
                    notified_ids.extend([dlc["id"] for dlc in missed_content if dlc.get("id")])
                    send_game_to_qstush(0, body)
                    update_one_item_in_db(item)
                    continue
                
                # side content tomorrow
                upcoming_side_dates = []
                for dlc in all_content:
                    dlc_id = dlc.get("id")
                    try:
                        dlc_release = datetime.fromtimestamp(dlc.get("first_release_date"), timezone.utc)
                    except TypeError:
                        dlc_release = False
                    if dlc_release and dlc_release.date() == datetime.now(timezone.utc).date() + timedelta(days=1):
                        if dlc_id and dlc_id not in item.get("notified_content_ids", []):
                            upcoming_side_dates.append(dlc)

                if upcoming_side_dates:
                    body = {
                        "id": game.get("id"),
                        "media_type": "game",
                        "title": game.get("name", ""),
                        "overview": game.get("summary", ""),
                        "poster_path": (game.get("cover") or {}).get("image_id"),
                        "genres": game.get("genres", []),
                        "involved_companies": game.get("involved_companies", []),
                        "platforms": game.get("platforms", []),
                        "content": upcoming_side_dates
                    }
                    notified_ids = item.setdefault("notified_content_ids", [])
                    notified_ids.extend([dlc["id"] for dlc in upcoming_side_dates if dlc.get("id")])
                    if upcoming_side_dates[0].get("first_release_date"):
                        time_in_sec = max(0, int(upcoming_side_dates[0]["first_release_date"] - datetime.now(timezone.utc).timestamp()))
                    else:
                        time_in_sec = 0
                    send_game_to_qstush(time_in_sec, body)
                    
                update_one_item_in_db(item)
        except Exception as e:
            continue
    return jsonify({"success": "true", "message": "check_game checked successfully"}), 200
    
    
    
@app.route('/api/notification/game', methods=['POST'])
def send_game_notification():
    try:
        auth_header = request.headers.get("authorization", "")
        if not auth_header == f"Bearer {os.environ.get('PASSWORD')}":
            return jsonify({'error': 'Unauthorized'}), 401

        body = request.get_json() or {}
        if body.get("release_dates"):

            item = get_item_data_from_db(body)
            item["released"] = True
            item["status"] = "Released"
            update_one_item_in_db(item)

            name = body.get("title")
            poster = f"https://images.igdb.com/igdb/image/upload/t_original/{body.get("poster_path", "")}.jpg"

            developer = []
            involved_companies = body.get('involved_companies', [])
            for companie in involved_companies:
                if companie.get("developer"):
                    developer.append(companie.get("company", {}).get("name", ""))
            developer = ", ".join(developer)

            release_dates = "Error"
            raw_release_date = body.get('release_dates')[0]

            if raw_release_date.get('date'):
                release_dates = datetime.fromtimestamp(raw_release_date.get('date'), timezone.utc).date().isoformat()

            platforms = []
            if body.get("platforms"):
                for platform in body.get("platforms"):
                   platforms.append(platform.get("abbreviation"))
                platforms = ", ".join(platforms)
            else:
                platforms = "Unknown(?)"

            genres = []
            if body.get("genres"):
                for genre in body.get("genres"):
                    genres.append(genre.get("name", ""))
                genres = ", ".join(genres)
            else:
                genres = "Unknown(?)"

            discord_msg = {
              "content": "🎮 **New Game Released!**",
              "embeds": [
                {
                  "title": name,
                  "description": "Now available to play.",
                  "color": 15418782,
                  "fields": [
                    {
                      "name": "Release Date",
                      "value": f"`{release_dates}`",
                      "inline": True
                    },
                    {
                      "name": "Developer",
                      "value": developer or "Unknown(?)",
                      "inline": True
                    },
                    {
                      "name": "Platforms",
                      "value": platforms
                    },
                    {
                      "name": "Genres",
                      "value": genres
                    }
                  ],
                  "footer": {
                    "text": "Game Release Notification"
                  },
                  "timestamp": datetime.now(timezone.utc).isoformat(),
                  "image": {
                    "url": poster
                  }
                }
              ],
              "attachments": []
            }
            item = get_item_data_from_db(body)
            if item.get("notifications"):
                requests.post(DISCORD_URL, json=discord_msg)

        elif body.get("content"):
            content = body.get("content")[0]

            name = body.get("title")
            content_type = content.get("game_type", {}).get('type')
            release_date = datetime.fromtimestamp(content.get("first_release_date"), timezone.utc).date().isoformat()
            expansion_title = content.get('name') or "Unknown(?)"
            poster = f"https://images.igdb.com/igdb/image/upload/t_cover_big/{(content.get('cover') or {}).get('image_id') or content.get('cover')}.jpg"


            discord_msg = {
              "content": f"🧩 **New {content_type or "DLC / Expansion"} Released!**",
              "embeds": [
                {
                  "title": name,
                  "description": "New downloadable content is now available.",
                  "color": 5814783,
                  "fields": [
                    {
                      "name": "Type",
                      "value": f"`{content_type or "Unknown(?)"}`",
                      "inline": True
                    },
                    {
                      "name": "Release Date",
                      "value": f"`{release_date}`",
                      "inline": True
                    },
                    {
                      "name": "Expansion Title",
                      "value": f"**{expansion_title}**"
                    }
                  ],
                  "footer": {
                    "text": "Game DLC Notification"
                  },
                  "timestamp": datetime.now(timezone.utc).isoformat(),
                  "thumbnail": {
                    "url": poster
                  }
                }
              ],
              "attachments": []
            }
            item = get_item_data_from_db(body)
            if item.get("notifications"):
                requests.post(DISCORD_URL, json=discord_msg)
        else:
            return jsonify({"success": "false", "message": "game notification was not send"}), 200



        return jsonify({"success": "true", "message": "game notification send successfully"}), 200
    except Exception as e:
        return jsonify({"success": "false", "message": f"{e}"}), 500

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

        response = requests.get(f"https://api.themoviedb.org/3/movie/{movie_id}?api_key={TMDB_API_KEY}&append_to_response=keywords,release_dates,videos")
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


        return jsonify(movie), 200
    except Exception as e:
        return jsonify({"success": False, "message": f"{e}"}), 500


@app.route('/api/sync/stremio', methods=['GET'])
def add_media_from_stremio():
    try:
        
        response = requests.post(
            UPSTASH_REDIS_REST_URL,
            headers=headers,
            json=["HGET", "stremio", "ignor_list"]
        )
        ignor_list = json.loads(response.json()['result'])
        
        body = {
            "authKey": STREMIO_AUTHKEY,
            "collection": "libraryItem",
            "all": True
        }
        response = requests.post("https://api.strem.io/api/datastoreGet", json=body, headers=stremio_headers)

        data = response.json()
        result = data.get("result") or []
        sorted_list = sorted(result, key=lambda item: item['_mtime'], reverse=True)
        current_libery = [item for item in sorted_list if not item.get('removed')]
        history = [item for item in sorted_list if item.get('state').get('timesWatched')]
        watched_today = [item for item in history if datetime.fromisoformat(item.get('_mtime')).date() == datetime.now(timezone.utc).date()]
        print([item.get('name') for item in watched_today])
        # print(sorted_list[0])
        for item in watched_today:
            id = ""
            media_type = ""
            if (item.get('_id', "")).startswith("tt"):
                response = requests.get(f"https://api.themoviedb.org/3/find/{item.get('_id')}?external_source=imdb_id&api_key={TMDB_API_KEY}")
                item_tmdb = response.json() or {}
                item_tmdb = item_tmdb.get("movie_results") or item_tmdb.get("movie_results") or item_tmdb.get("tv_results") or item_tmdb.get("tv_episode_results") or item_tmdb.get("tv_season_results") or {}
                if item_tmdb:
                    item_tmdb = item_tmdb[0]
                    id = item_tmdb.get("id") or ""
                    media_type = item_tmdb.get("media_type") or ""
            if media_type and id:
                if f"{media_type}:{id}" not in ignor_list:
                    ignor_list.append(f"{media_type}:{id}")
                    get_data_for_add_item(id, media_type)
                
        requests.post(
            UPSTASH_REDIS_REST_URL,
            headers=headers,
            json=["HSET", "stremio", "ignor_list", json.dumps(ignor_list)]
        )

        return jsonify({"success": True, "message": f"successfly sync the data"}), 500
    except Exception as e:
        return jsonify({"success": False, "message": f"{e}"}), 500
    
    
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
                      "options": ["Sort: Newest First",  "Sort: Oldest First", "Sort: Release Date Newest First", "Sort: Release Date Oldest First", "Sort: Alphabetical", "Availble on Digital", "Not Availble on Digital", "Action", "Adventure", "Animation", "Comedy", "Crime", "Documentary", "Drama", "Family", "Fantasy", "History", "Horror", "Music", "Mystery", "Romance", "Science Fiction", "TV Movie", "Thriller", "War", "Western"]
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
                      "options": ["Sort: Newest First",  "Sort: Oldest First", "Sort: First Air Date Newest First", "Sort: First Air Date Oldest First", "Sort: Last Air Date Newest First", "Sort: Last Air Date Oldest First", "Sort: Alphabetical", "Action & Adventure", "Animation", "Comedy", "Crime", "Documentary", "Drama", "Family", "Kids", "Mystery", "News", "Reality", "Sci-Fi & Fantasy", "Soap", "Talk", "War & Politics", "Western"]
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
        selected_option = "Sort: Newest First"
        
        if "/" in clean_path:
            catalog_id, args_string = clean_path.split("/", 1)
        
            parsed_args = urllib.parse.parse_qs(args_string)
            if "genre" in parsed_args:
                selected_option = parsed_args["genre"][0]
        
        if catalog_id == "my_custom_catalog":
            db_data = get_db_data_v2()
            db_data = sorted(db_data, key=lambda item : item.get("added_date", ""), reverse=True)


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
                db_data = sorted(db_data, key=lambda item: item.get("last_air_date", "") or "", reverse=True)
            elif selected_option == "Sort: Last Air Date Oldest First":
                db_data = sorted(db_data, key=lambda item: item.get("last_air_date", "") or "")
            elif selected_option == "Availble on Digital":
                db_data = [item for item in db_data if item.get("digital", "")]
            elif selected_option == "Not Availble on Digital":
                db_data = [item for item in db_data if not item.get("digital", "")]
            else:
                filtered_data = []
                for item in db_data:
                    item_genres = item.get("genres", [])
                    genre_names = [g.get("name") for g in item_genres if g.get("name")]
                    if selected_option in genre_names:
                        filtered_data.append(item)
                db_data = filtered_data


            if content_type == "movie":
                movies = []
                for movie in db_data:
                    if movie["media_type"] == "movie":
                        poster_path = movie.get("poster_path")
                        movies.append({
                            "id": f"tmdb:{movie['id']}", 
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
        requests.post(DISCORD_URL, json={"error": e})
        
            
