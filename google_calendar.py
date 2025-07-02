import concurrent
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Flask, request, jsonify, Response, session
from google.oauth2 import service_account
from googleapiclient.discovery import build
from datetime import datetime, timedelta
import time
import sys
import io
import requests
from dotenv import load_dotenv
import os
import json
import re
from flask_cors import CORS
import pytz
from functools import lru_cache
from datetime import timedelta

# Cache configuration
CACHE_TTL = timedelta(minutes=15)
TRANSLATION_CACHE_SIZE = 300  # Number of translations to cache
QUERY_CACHE_SIZE = 100  # Number of parsed queries to cache   

@lru_cache(maxsize=100)
def cached_availability_check(room_name: str, start_time: str, end_time: str):
    """Cache results for 15 minutes to avoid repeated API calls"""
    return is_room_available(room_name, start_time, end_time)

def get_availability(room_name, start_time, end_time):
    # Create a consistent cache key
    cache_key = f"{room_name}|{start_time}|{end_time}"
    return cached_availability_check(room_name, start_time, end_time)

@lru_cache(maxsize=TRANSLATION_CACHE_SIZE)
def cached_translate_to_english(text):
    return translate_to_english(text)

@lru_cache(maxsize=TRANSLATION_CACHE_SIZE)
def cached_translate_to_chinese(text):
    return translate_to_chinese(text)

@lru_cache(maxsize=QUERY_CACHE_SIZE)
def cached_parse_query(query):
    return parse_natural_query_with_deepseek(query)

def fetch_events(calendar_id, start, end):
    try:
        events = query_events_with_retry(service, calendar_id, start, end).get("items", [])
        return calendar_id, {"events": events, "exception": None}
    except Exception as e:
        return calendar_id, {"events": [], "exception": str(e)}

def batch_check_rooms(room_ids, start, end):
    """Sequential version of room checks without threading."""
    # results = {}
    # for calendar_id in room_ids:
    #     try:
    #         events = query_events_with_retry(service, calendar_id, start, end).get("items", [])
    #         results[calendar_id] = {
    #             "events": events,
    #             "exception": None
    #         }
    #     except Exception as e:
    #         results[calendar_id] = {
    #             "events": [],
    #             "exception": str(e)
    #         }
    # return results
    results = {}

    def fetch_room_events(calendar_id):
        try:
            events = query_events_with_retry(service, calendar_id, start, end).get("items", [])
            return (calendar_id, {"events": events, "exception": None})
        except Exception as e:
            return (calendar_id, {"events": [], "exception": str(e)})

    with ThreadPoolExecutor(max_workers=8) as executor:
        future_to_cal = {executor.submit(fetch_room_events, cal_id): cal_id for cal_id in room_ids}
        for future in as_completed(future_to_cal):
            calendar_id, result = future.result()
            results[calendar_id] = result

    return results


# 30 min prep time => fixed
# Memory of Chat
# Cantonese Check
# Calendar add event to officernd to check if it syncs
# recommendation time slot
# Add logo and change to english if english detected => fixed


load_dotenv()
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

# Fix Unicode printing on Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# --- CONFIG ---
SERVICE_ACCOUNT_FILE = 'glass-house-at-lung-wah-0932d8d8f3ea.json'
SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']

# Authenticate using service account
credentials = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE,
    scopes=SCOPES
)

# Build the Google Calendar API service
service = build('calendar', 'v3', credentials=credentials)

# Calendar name mapping
calendar_map = {
    "c_cd2a79863a870ab64cc5962be028d9a66169a07b039f47980f1eaf60ff30a081@group.calendar.google.com": "DI Whole Area (all rooms)",
    "c_5cfa09bb8ea0490186e63536b3368a6a81a99cdee4bf2d18f9e2fc87b18503c6@group.calendar.google.com": "DI_Dream + Impact Room",
    "c_001095b45acd48a13555ee8316d7b0d05c6f567c620aaf9e20aa2119e5d52a06@group.calendar.google.com": "DI_Dream Room",
    "c_aa624e124e64c1f6ec48b681df3f6561b253f44e79711383a0aa25ec99f1f9ee@group.calendar.google.com": "DI_Impact Room",
    "c_9d20446676a2544bc98493b6c5838c7fd794188b69249407496409e1a64adbd9@group.calendar.google.com": "DI_Open Area",
    "c_12015323ccadc4601f29872fb36ac2c63ece9335a79b1f0fe99b4dd99161d792@group.calendar.google.com": "DI_Pantry",
    "c_7b64193e05008860c5dd15ccb0e82d4f652386af55bc861bcdcbe8af4a7caadf@group.calendar.google.com": "DI_Synergy (A&B) + Dream + Impact Room",
    "c_35b48d8c158778e6815a259d83f023d61fbfd8166139ee350b35b301fddc8ad3@group.calendar.google.com": "DI_Synergy Room A ",
    "c_5f3e7393bf2c2e74b503fea43955d3914db2c70b2703c513c2006032bbdf919c@group.calendar.google.com": "DI_Synergy Room A + B",
    "c_56c10cfa6a2912bd0bffd83e4cc307832fa4f63817c9430fb900834ebd267e23@group.calendar.google.com": "DI_Synergy Room B"
}

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

@app.route("/")
def home():
    return "✅ Flask Calendar API is running. Use /check with parameters."

def get_calendar_id_by_name(room_name):
    """
    Return the calendar ID given a human-readable room name.
    """
    for cal_id, name in calendar_map.items():
        if name.strip().lower() == room_name.strip().lower():
            return cal_id
    return None

def query_events_with_retry(service, calendar_id, start_time, end_time, retries=2, delay=0.5):
    """Retry querying events, handle exceptions and retries."""
    for attempt in range(retries):
        try:
            request = service.events().list(
                calendarId=calendar_id,
                timeMin=start_time,
                timeMax=end_time,
                singleEvents=True,
                orderBy='startTime'
            )
            return request.execute(num_retries=1)
        except Exception as e:
            if attempt == retries - 1:
                raise e
            time.sleep(delay)

def get_rooms_to_check(room_name):
    """Get all rooms that need to be checked including groups"""
    ROOM_GROUPS = {
        "DI Whole Area (all rooms)": 
            ["DI_Dream Room", "DI_Impact Room", "DI_Open Area", "DI_Pantry", "DI_Synergy Room A", "DI_Synergy Room B"],
        "DI_Dream + Impact Room": 
            ["DI_Dream Room", "DI_Impact Room"],
        "DI_Synergy (A&B) + Dream + Impact Room": 
            ["DI_Synergy Room A", "DI_Synergy Room B", "DI_Dream Room", "DI_Impact Room"],
        "DI_Synergy Room A + B": 
            ["DI_Synergy Room A", "DI_Synergy Room B"]
    }    
    PARENT_GROUPS = {
        "DI_Dream Room": 
            ["DI_Dream + Impact Room", "DI_Synergy (A&B) + Dream + Impact Room", "DI Whole Area (all rooms)"],
        "DI_Impact Room": 
            ["DI_Dream + Impact Room", "DI_Synergy (A&B) + Dream + Impact Room", "DI Whole Area (all rooms)"],
        "DI_Synergy Room A": 
            ["DI_Synergy Room A + B", "DI_Synergy (A&B) + Dream + Impact Room", "DI Whole Area (all rooms)"],
        "DI_Synergy Room B":
            ["DI_Synergy Room A + B", "DI_Synergy (A&B) + Dream + Impact Room", "DI Whole Area (all rooms)"],
        "DI_Open Area": 
            ["DI Whole Area (all rooms)"],
        "DI_Pantry": 
            ["DI Whole Area (all rooms)"]
    }
    
    rooms = {room_name}
    rooms.update(ROOM_GROUPS.get(room_name, []))
    rooms.update(PARENT_GROUPS.get(room_name, []))
    return rooms

def is_room_available(room_name, start_time, end_time, visited_rooms=None):
    if visited_rooms is None:
        visited_rooms = set()
    if room_name in visited_rooms:
        return None, f"Suggestion loop detected for {room_name}", None
    visited_rooms.add(room_name)

    rooms_to_check = get_rooms_to_check(room_name)

    # Buffer for safety
    try:
        req_start = datetime.fromisoformat(start_time)
        req_end = datetime.fromisoformat(end_time)
        buffer_start = (req_start - timedelta(minutes=30)).isoformat()
        buffer_end = (req_end + timedelta(minutes=30)).isoformat()
    except Exception as e:
        return None, f"Invalid datetime: {str(e)}", None

    # Map to calendar ids
    room_mapping = {}
    for room in rooms_to_check:
        room_id = get_calendar_id_by_name(room)
        if not room_id:
            return None, f"Calendar not found: {room}", None
        room_mapping[room_id] = room

    batch_results = batch_check_rooms(room_mapping.keys(), buffer_start, buffer_end)

    conflicts = []
    for room_id, result in batch_results.items():
        if result['exception']:
            return None, f"API error for {room_mapping[room_id]}: {result['exception']}", None
        for event in result['events']:
            try:
                event_start = datetime.fromisoformat(event['start'].get('dateTime', event['start'].get('date')))
                event_end = datetime.fromisoformat(event['end'].get('dateTime', event['end'].get('date')))
                # Check overlap with 30 min buffer
                if req_start < (event_end + timedelta(minutes=30)) and req_end > (event_start - timedelta(minutes=30)):
                    conflicts.append({
                        'room': room_mapping[room_id],
                        'title': event.get('summary', 'No Title'),
                        'start': event_start.isoformat(),
                        'end': event_end.isoformat(),
                        'note': '30-min buffer conflict'
                    })
            except Exception:
                continue

    available = len(conflicts) == 0
    suggestion = None

    # Shared rooms fallback
    SHARED_ROOM_GROUPS = {
        "DI_Shared_Rooms": [
            "DI_Dream Room",
            "DI_Impact Room",
            "DI_Open Area",
            "DI_Pantry",
            "DI_Synergy Room B"
        ]
    }

    # Interchangeable combos fallback
    INTERCHANGEABLE_COMBOS = {
        "DI_Dream + Impact Room": "DI_Synergy Room A + B",
        "DI_Synergy Room A + B": "DI_Dream + Impact Room"
    }

    if not available:
        # Check shared rooms group fallback
        for group_rooms in SHARED_ROOM_GROUPS.values():
            if room_name in group_rooms:
                for alt_room in group_rooms:
                    if alt_room == room_name:
                        continue
                    alt_available, _, _ = is_room_available(alt_room, start_time, end_time, visited_rooms)
                    if alt_available:
                        suggestion = {"suggested_room": alt_room}
                        break
                if suggestion:
                    break

    if not suggestion and not available and room_name in INTERCHANGEABLE_COMBOS:
        alt_combo = INTERCHANGEABLE_COMBOS[room_name]
        alt_available, _, _ = is_room_available(alt_combo, start_time, end_time, visited_rooms)
        if alt_available:
            suggestion = {"suggested_room": alt_combo}

    return (True, [], None) if available else (False, conflicts, suggestion)


@app.route("/check", methods=["POST"])
def check_availability():
    data = request.get_json() or {}
    room = data.get("room")
    start_time = data.get("start")
    end_time = data.get("end")

    if not all([room, start_time, end_time]):
        return jsonify({"error": "Missing parameters"}), 400

    try:
        available, conflicts, suggestion = is_room_available(room, start_time, end_time)
    except Exception as e:
        return jsonify({"error": f"Failed to check availability: {str(e)}"}), 500

    response = {
        "room": room,
        "available": available,
        "conflicts": conflicts if not available else [],
    }
    if suggestion:
        response["suggestion"] = suggestion

    return jsonify(response)

    
def translate_to_english(text):
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }

    prompt = f"Translate this to English (if it's already English, return as-is):\n{text}"
    data = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "user", "content": prompt}
        ]
    }

    response = requests.post(DEEPSEEK_API_URL, headers=headers, json=data)
    response.raise_for_status()
    return response.json()['choices'][0]['message']['content'].strip()

def translate_to_chinese(text):
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }

    prompt = f"請將以下英文翻譯成繁體中文:\n{text}"
    data = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "user", "content": prompt}
        ]
    }

    response = requests.post(DEEPSEEK_API_URL, headers=headers, json=data)
    response.raise_for_status()
    return response.json()['choices'][0]['message']['content'].strip()

def is_chinese(text):
    """Detect if the query contains Chinese characters."""
    return any('\u4e00' <= char <= '\u9fff' for char in text)
    
def parse_natural_query_with_deepseek(query):
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }
    today = datetime.now(pytz.timezone("Asia/Hong_Kong")).date().isoformat()
    system_prompt = f"""You are a helpful assistant that extracts meeting room booking information from natural language queries.
    If date is not mentioned, assume today's date: {today}.
    Extract the following information as JSON **or list of objects if multiple bookings are mentioned**:
    - room: The room name (must match one of the valid room names exactly)
    - start: ISO 8601 datetime with timezone
    - end: ISO 8601 datetime with timezone
    
    Valid room names:
    "DI Whole Area (all rooms)",
    "DI_Dream + Impact Room",
    "DI_Dream Room",
    "DI_Impact Room",
    "DI_Open Area",
    "DI_Pantry",
    "DI_Synergy (A&B) + Dream + Impact Room",
    "DI_Synergy Room A",
    "DI_Synergy Room B",
    "DI_Synergy Room A + B"
    
    Chinese room name mappings:
    "夢想室" → "DI_Dream Room"
    "影響室" → "DI_Impact Room"
    "綜合區" → "DI Whole Area (all rooms)"
    "開放區" → "DI_Open Area"
    "茶水間" → "DI_Pantry"
    "協作室A" → "DI_Synergy Room A"
    "協作室B" → "DI_Synergy Room B"
    "協作室A+B" → "DI_Synergy Room A + B"
    
    Example output for "6月28日下午3點到4點夢想室有冇人用？":
    [
        {{
        "room": "DI_Dream Room",
        "start": "2025-06-28T15:00:00+08:00",
        "end": "2025-06-28T16:00:00+08:00"
        }},
        {{
        "room": "DI_Dream Room",
        "start": "2025-06-29T15:00:00+08:00",
        "end": "2025-06-29T16:00:00+08:00"
        }}
    ]

    
    Return ONLY the JSON output, nothing else."""

    data = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": query}
        ],
        "temperature": 0.1  # More deterministic output
    }

    try:
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=data)
        response.raise_for_status()
        content = response.json()['choices'][0]['message']['content'].strip()

        # Try to extract a list of JSON objects
        list_match = re.search(r'\[\s*\{.*?\}\s*\]', content, re.DOTALL)
        if list_match:
            return json.loads(list_match.group(0))

        # Fallback: try to extract a single object and wrap in a list
        single_match = re.search(r'\{.*?\}', content, re.DOTALL)
        if single_match:
            return [json.loads(single_match.group(0))]

        return {"error": "Could not extract booking information from response"}

    except Exception as e:
        return {"error": f"API request failed: {str(e)}"}

def simplify_datetime(dt_str):
    """
    Convert ISO8601 datetime string (with optional timezone) to 'YYYY-MM-DD HH:MM' format.
    """
    try:
        dt = datetime.fromisoformat(dt_str)
        return dt.strftime("%Y-%m-%d: %H:%M")
    except Exception:
        # If parsing fails, return original string as fallback
        return dt_str  

def simplify_conflicts(conflicts):
    for c in conflicts:
        if "start" in c:
            c["start"] = simplify_datetime(c["start"])
        if "end" in c:
            c["end"] = simplify_datetime(c["end"])
    return conflicts

def classify_query_intent(query):
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }

    prompt = """
        You are an assistant that classifies user input into one of the following categories:

            - greeting
            - booking_query

            Only respond with the lowercase label. For example, just say: greeting
        """
    data = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": query}
        ],
        "temperature": 0.1
    }

    try:
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=data)
        response.raise_for_status()
        label = response.json()["choices"][0]["message"]["content"].strip().lower()
        return label
    except Exception as e:
        return "unknown"

@app.route("/ask", methods=["POST"])
def ask():
    data = request.get_json()
    query = data.get("query", "").strip()

    if not query:
        return jsonify({"error": "Missing 'query' field"}), 400

    intent = classify_query_intent(query)
    query_is_chinese = is_chinese(query)

    if intent == "greeting":
        return jsonify(["Hello! How can I help you with meeting room availability today?"])

    elif intent == "booking_query":
        # return jsonify(["I can help you check room availability. Please ask me about a room and time."])

        # Step 1: Translation (with caching)
        try:
            translated_query = (
                cached_translate_to_english(query) 
                if query_is_chinese 
                else query
            )
        except Exception as e:
            return jsonify({"error": f"Translation failed: {str(e)}"}), 500

        
        # Step 2: Query Parsing (with caching)
        parsed = cached_parse_query(translated_query)
        
        if isinstance(parsed, dict) and parsed.get("error"):
            error_msg = parsed["error"]
            if query_is_chinese:
                error_msg = cached_translate_to_chinese(error_msg)
            return jsonify({"error": error_msg}), 400

        # Normalize to list
        parsed_list = [parsed] if isinstance(parsed, dict) else parsed
        for item in parsed_list:
            if not item.get("room") and session.get("last_room"):
                item["room"] = session["last_room"]
            if not item.get("start") and session.get("last_start"):
                item["start"] = session["last_start"]
            if not item.get("end") and session.get("last_end"):
                item["end"] = session["last_end"]
        
        
        # Process results
        results = []
        for item in parsed_list:
            if not all(item.get(key) for key in ["room", "start", "end"]):
                msg = "Missing room, start, or end time in parsed data"
                if query_is_chinese:
                    msg = cached_translate_to_chinese(msg)
                return jsonify({"error": msg}), 400
            
            session['last_room'] = item["room"]
            session['last_start'] = item["start"]
            session['last_end'] = item["end"]
            
            # Check availability (with batch processing)
            available, conflicts, suggestion = is_room_available(
                item["room"], 
                item["start"], 
                item["end"]
            )

            if available is None:
                error_msg = conflicts if isinstance(conflicts, str) else "Unknown error"
                if query_is_chinese:
                    error_msg = cached_translate_to_chinese(error_msg)
                return jsonify({"error": error_msg}), 500

            result = {
                "room": item["room"],
                "start": simplify_datetime(item["start"]),
                "end": simplify_datetime(item["end"]),
                "available": available,
                "conflicts": simplify_conflicts(conflicts) if not available else []
            }

            if not available and suggestion:
                result["suggestion"] = suggestion  # e.g. {"suggested_room": "DI_Pantry"}

            results.append(result)

        # Step 3: Response Translation (if needed)
        response_data = json.dumps(results, ensure_ascii=False, indent=2)
        if query_is_chinese:
            try:
                translated_response = cached_translate_to_chinese(response_data)
                return Response(translated_response, mimetype="application/json")
            except Exception:
                pass  # Fall through to return English response

        return Response(response_data, mimetype="application/json")
    
if __name__ == "__main__":
    load_dotenv()  # Load environment variables from .env file
    # Makes the server accessible to other devices on the same Wi-Fi
    app.run(host="0.0.0.0", port=5000, debug=True)
