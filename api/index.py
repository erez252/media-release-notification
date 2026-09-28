import os
import json
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from datetime import datetime, timezone, timedelta
app = Flask(__name__)
CORS(app)  # Handles CORS preflight headers automatically

UPSTASH_REDIS_REST_URL = os.environ.get('UPSTASH_REDIS_REST_URL')
UPSTASH_REDIS_REST_TOKEN = os.environ.get('UPSTASH_REDIS_REST_TOKEN')
TMDB_API_KEY = os.environ.get('TMDB_API_KEY')
DISCORD_URL = os.environ.get('DISCORD_URL')
QSTASH_TOKEN = os.environ.get('QSTASH_TOKEN')
QSTASH_URL = os.environ.get('QSTASH_URL')
IGDB_CLIENT_ID = os.environ.get('IGDB_CLIENT_ID')
IGDB_ACCESS_TOKEN = os.environ.get('IGDB_ACCESS_TOKEN')

headers = {"Authorization": f"Bearer {UPSTASH_REDIS_REST_TOKEN}"}
qstash_header= {"Authorization": f"Bearer {QSTASH_TOKEN}"}

def is_authorized(body):
    user_password = body.get("password")
    return isinstance(user_password, str) and user_password == os.environ.get('PASSWORD')



def get_db_data():
    res = requests.get(f"{UPSTASH_REDIS_REST_URL}/get/watchlist", headers=headers)
    db_data = res.json().get("result")
    return json.loads(db_data) if db_data else []

def get_db_data_v2():
    response = requests.post(
    UPSTASH_REDIS_REST_URL,
    headers=headers,
    json=["HVALS", "Watchlist-V2"]
    )

    raw_list = response.json()["result"]

    watchlist = [json.loads(item) for item in raw_list if item.startswith('{')]
    
    return watchlist

    
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
    
    response = requests.post(qstash_publish_endpoint, headers=qstash_task_header, json=qstash_task_payload)

def get_game_results(query):
    
    headers = {
        "Content-Type": "application/json",
        'Client-ID': IGDB_CLIENT_ID,
        'Authorization': f"Bearer {IGDB_ACCESS_TOKEN}"
    }
    
    fields = "name,cover.image_id,first_release_date,game_type,game_status.status,genres.name,hypes,summary,first_release_date,rating,rating_count"
    filters = "themes != (42) & game_type = (0, 8, 9, 10)"
    
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
    # print(game)
    
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
    if digital:
        status = "Released"
    
    cover = game.get("cover")
    poster_path = cover.get("image_id", "") if cover else ""
    
    vote_average = game.get("rating", 0)
    if vote_average:
        vote_average = vote_average / 10
        
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
            'popularity': game.get("hype", 0),
            "vote_average": vote_average,
            "vote_count": game.get("rating_count", 0),
            "added_date": datetime.now(timezone.utc).isoformat()
        }
    return(custom_data)
    
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
    
    
    # if movie_type and movie_id and type(movie_id) is int:
    #     match = False
    #     db_data = get_db_data_v2()
    #     for movie in db_data:
    #         if movie.get("media_type") == movie_type and movie.get("id") == movie_id:
    #             db_data.remove(movie)
    #             match = True
    #             break
    #     if not match:
    #         return jsonify({"error": "Unprocessable Entity", "message": "Cannot delete item because it does not exist."}), 422
    #     update_db(db_data)
    #     return jsonify({"message": f"Removed item with an id of {movie_id}"}), 200
    # else:
    #     return jsonify({"error": "Bad Request", "message": "One or more missing required parameters"}), 400


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



        movie_response = requests.get(f"https://api.themoviedb.org/3/{media_type}/{media_id}?api_key={TMDB_API_KEY}")
        if movie_response.status_code == 404:
            return jsonify({"error": "No results"}), 404

        # justwatch_data_url = f"https://api.themoviedb.org/3/{media_type}/{media_id}/watch/providers?api_key={TMDB_API_KEY}"
        # response = requests.get(justwatch_data_url)
        # digital = False
        # watch_data = {}
        # if response.status_code == 200:
        #         watch_data = response.json()
        # if watch_data.get("results", []):
        #     digital = True
            
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
              
        
        db_data.append(movie_data)
        update_db(db_data)
        # response = requests.post(UPSTASH_REDIS_REST_URL, headers=headers, json=["SET", "watchlist", json.dumps(db_data)])
        return jsonify({"success": "true", "message": "Added the media"}), 200
        # if response.status_code == 200:

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
                        send_movie_notification(item, dates['release_date'])
                    

                    
        update_db(db_data)
        return jsonify({"success": "true", "message": "check_movie checked successfully"}), 200
    except Exception as e:
        return jsonify({"error": "Bad Gateway", "message": f"Server error: {e}"}), 502
                

def check_movie_old():
    try:
        limit = 20
        auth_header = request.headers.get("authorization", "")
        if not auth_header == f"Bearer {os.environ.get('PASSWORD')}":
            return jsonify({'error': 'Unauthorized'}), 401
        
        db_data = get_db_data_v2()
        needs_update = []
        for item in db_data:

                if limit and item.get("media_type") == "movie" and not item.get("digital") and (not item.get("last_checked") or datetime.fromisoformat(item.get("last_checked")) < datetime.now(timezone.utc) - timedelta(hours=8)):
                    item["last_checked"] = datetime.now(timezone.utc).isoformat()
                    

                    is_digital = check_if_digital(item.get('id'))
                    limit -= 1
                    if is_digital:
                        item["digital"] = True
                        needs_update.append(item)
        if needs_update:
            for movie in needs_update:
                
                # get genres
                genres = []
                for genre in movie.get('genres', []):
                    genres.append(genre["name"])
                    
                # discord msg
                discord_msg = {
                  "content": "🎥 **New Movie Digital Release!**",
                  "embeds": [
                    {
                      "title": movie.get('title'),
                      "description": "Now available to stream.",
                      "color": 10038562,
                      "fields": [
                        {
                          "name": "Release Date",
                          "value": f"`{movie.get('release_date')}`",
                          "inline": True
                        },
                        {
                          "name": "Runtime",
                          "value": f"`{movie.get('runtime')}`",
                          "inline": True
                        },
                        {
                          "name": "Genres",
                          "value": f"{', '.join(genres)}",
                          "inline": False
                        }
                      ],
                      "image": {
                        "url": f"https://image.tmdb.org/t/p/w780{movie.get("poster_path")}"
                      },
                      "footer": {
                        "text": "Movie Release Notification"
                      },
                      "timestamp": f"{datetime.now().isoformat()}"
                    }
                  ]
                }
                
                requests.post(DISCORD_URL, json=discord_msg)
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
    
    db_data = get_db_data_v2()
    for media in db_data:
        if str(media['id']) == str(movie['id']) and media['media_type'] == movie['media_type']:
            media['digital'] = True
    update_db(db_data)
    
    send_movie_notification(movie, time)
    
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
                        new_episodes.append({'show_name': show.get('title'), 'season': ep.get('season'), 'episode': ep.get('number'), 'airstamp': ep.get("airstamp"), 'airtime': ep.get('airtime'), 'type': ep.get("type", ""), 'name': ep.get("name", ""), 'poster_path': show.get("poster_path", "")})
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


            item['last_updated'] = datetime.now(timezone.utc).isoformat()
                
            
    
    update_db(db_data)
    return jsonify({"success": "true", "message": "Updated the media"}), 200
