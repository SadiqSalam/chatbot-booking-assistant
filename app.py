from flask import Flask, request, jsonify, Response, session
from google.oauth2 import service_account
from googleapiclient.discovery import build
from datetime import datetime, timedelta
import pytz
import os
import json
import time
import requests
import re
from functools import lru_cache
from dotenv import load_dotenv
from flask_cors import CORS
import sys
import io
from flask import render_template


    
http_session = requests.Session()

import time

class Timer:
    def __init__(self):
        self.start = time.perf_counter()
        self.marks = [("start", self.start)]

    def mark(self, label):
        now = time.perf_counter()
        self.marks.append((label, now))

    def summary(self):
        out = []
        for i in range(1, len(self.marks)):
            label, t = self.marks[i]
            prev_label, prev_t = self.marks[i - 1]
            out.append(f"{prev_label} -> {label}: {t - prev_t:.2f}s")
        total = self.marks[-1][1] - self.marks[0][1]
        out.append(f"Total time: {total:.2f}s")
        return "\n".join(out)

# --- Your existing constants, env, service setup ---
load_dotenv()
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# SERVICE_ACCOUNT_FILE = 'glass-house-at-lung-wah-0932d8d8f3ea.json'
SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']

# credentials = service_account.Credentials.from_service_account_file(
#     SERVICE_ACCOUNT_FILE, scopes=SCOPES
# )
service_account_info = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
credentials = service_account.Credentials.from_service_account_info(service_account_info, scopes=SCOPES)

service = build('calendar', 'v3', credentials=credentials)

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
CORS(app)

app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret-key")  # Default fallback

# @app.route("/")
# def home():
#     return "✅ Flask Calendar API is running. Use /check with parameters."

@app.route("/")
def home():
    return render_template("calendarbi.html")

def get_calendar_id_by_name(room_name):
    """
    Return the calendar ID given a human-readable room name.
    """
    for cal_id, name in calendar_map.items():
        if name.strip().lower() == room_name.strip().lower():
            return cal_id
    return None

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
def cached_parse_query(query, memory_context=""):
    key = (query, memory_context)
    return parse_natural_query_with_deepseek(query, memory_context=memory_context)

@lru_cache(maxsize=QUERY_CACHE_SIZE)
def classify_query_intent_cached(query):
    return classify_query_intent(query)



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
    
    Example output for "is dream room free on June 28 3pm to 4pm？":
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
        response = http_session.post(DEEPSEEK_API_URL, headers=headers, json=data)
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

    response = http_session.post(DEEPSEEK_API_URL, headers=headers, json=data)
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

    response = http_session.post(DEEPSEEK_API_URL, headers=headers, json=data)
    response.raise_for_status()
    return response.json()['choices'][0]['message']['content'].strip()

def batch_check_rooms(room_ids, start, end):
    """Batch check availability for multiple rooms in parallel."""
    results = {}
    for calendar_id in room_ids:
        try:
            events = query_events_with_retry(service, calendar_id, start, end).get("items", [])
            results[calendar_id] = {
                "events": events,
                "exception": None
            }
        except Exception as e:
            results[calendar_id] = {
                "events": [],
                "exception": str(e)
            }
    return results

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
                    alt_available, _, _ = is_room_available_cached(alt_room, start_time, end_time, visited_rooms, checked_results={})
                    if alt_available:
                        suggestion = {"suggested_room": alt_room}
                        break
                if suggestion:
                    suggestion = {"Unfortunately, all rooms are booked"}
                    break

    if not suggestion and not available and room_name in INTERCHANGEABLE_COMBOS:
        alt_combo = INTERCHANGEABLE_COMBOS[room_name]
        alt_available, _, _ = is_room_available_cached(alt_combo, start_time, end_time, visited_rooms)
        if alt_available:
            suggestion = {"suggested_room": alt_combo}

    return (True, [], None) if available else (False, conflicts, suggestion)


def query_events_with_retry(service, calendar_id, start_time, end_time, retries=2, delay=0.5):
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

def get_calendar_id_by_name(room_name):
    for cal_id, name in calendar_map.items():
        if name.strip().lower() == room_name.strip().lower():
            return cal_id
    return None

def get_rooms_to_check(room_name):
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

# --- New: batch fetch all events from today forward, store locally for this request ---
def batch_fetch_events_until(room_ids, end_dt):
    """
    Fetch events starting from today 00:00:00+08:00 until provided end datetime (with buffer).
    """
    # tz = pytz.timezone("Asia/Hong_Kong")
    # now = datetime.now(tz)
    # start_of_today = datetime(now.year, now.month, now.day, 0, 0, 0, tzinfo=tz)

    # start_iso = start_of_today.isoformat()
    # end_iso = end_dt.isoformat()

    # results = {}

    # def fetch_room_events(cal_id):
    #     try:
    #         response = query_events_with_retry(service, cal_id, start_iso, end_iso)
    #         return cal_id, response.get("items", [])
    #     except Exception:
    #         return cal_id, []

    # with ThreadPoolExecutor(max_workers=8) as executor:
    #     futures = {executor.submit(fetch_room_events, cal_id): cal_id for cal_id in room_ids}
    #     for future in as_completed(futures):
    #         cal_id, events = future.result()
    #         results[cal_id] = events

    # return results
    tz = pytz.timezone("Asia/Hong_Kong")
    now = datetime.now(tz)
    start_of_today = datetime(now.year, now.month, now.day, 0, 0, 0, tzinfo=tz)

    start_iso = start_of_today.isoformat()
    end_iso = end_dt.isoformat()

    results = {}

    for cal_id in room_ids:
        try:
            response = query_events_with_retry(service, cal_id, start_iso, end_iso)
            results[cal_id] = response.get("items", [])
        except Exception:
            results[cal_id] = []

    return results

# --- Modified is_room_available to use cached events instead of live API calls ---
def is_room_available_cached(room_name, start_time, end_time, cached_events, visited_rooms=None, checked_results=None):
    
        
    if checked_results is None:
        checked_results = {}

    cache_key = f"{room_name}|{start_time}|{end_time}"
    if cache_key in checked_results:
        return checked_results[cache_key]
    
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
        buffer_start = req_start - timedelta(minutes=30)
        buffer_end = req_end + timedelta(minutes=30)
    except Exception as e:
        return None, f"Invalid datetime: {str(e)}", None

    # Map to calendar ids
    room_mapping = {}
    for room in rooms_to_check:
        room_id = get_calendar_id_by_name(room)
        if not room_id:
            return None, f"Calendar not found: {room}", None
        room_mapping[room_id] = room

    conflicts = []
    for room_id, room in room_mapping.items():
        events = cached_events.get(room_id, [])
        for event in events:
            try:
                event_start_str = event['start'].get('dateTime', event['start'].get('date'))
                event_end_str = event['end'].get('dateTime', event['end'].get('date'))
                event_start = datetime.fromisoformat(event_start_str)
                event_end = datetime.fromisoformat(event_end_str)

                # Check overlap with 30 min buffer
                if req_start < (event_end + timedelta(minutes=30)) and req_end > (event_start - timedelta(minutes=30)):
                    conflicts.append({
                        'room': room,
                        'title': event.get('summary', 'No Title'),
                        'start': event_start.isoformat(),
                        'end': event_end.isoformat(),
                        'note': '30-min buffer conflict'
                    })
            except Exception:
                continue

    available = len(conflicts) == 0
    suggestion = None

    SHARED_ROOM_GROUPS = {
        "DI_Shared_Rooms": [
            "DI_Dream Room",
            "DI_Impact Room",
            "DI_Open Area",
            "DI_Pantry",
            "DI_Synergy Room B"
        ]
    }

    INTERCHANGEABLE_COMBOS = {
        "DI_Dream + Impact Room": "DI_Synergy Room A + B",
        "DI_Synergy Room A + B": "DI_Dream + Impact Room"
    }

    if not available:
        # Check shared rooms fallback
        for group_rooms in SHARED_ROOM_GROUPS.values():
            if room_name in group_rooms:
                for alt_room in group_rooms:
                    if alt_room == room_name:
                        continue
                    alt_available, _, _ = is_room_available_cached(alt_room, start_time, end_time, cached_events, visited_rooms, checked_results)
                    if alt_available:
                        suggestion = {"suggested_room": alt_room}
                        break
                if suggestion:
                    break

    if not suggestion and not available and room_name in INTERCHANGEABLE_COMBOS:
        alt_combo = INTERCHANGEABLE_COMBOS[room_name]
        alt_available, _, _ = is_room_available_cached(alt_combo, start_time, end_time, cached_events, visited_rooms, checked_results)
        if alt_available:
            suggestion = {"suggested_room": alt_combo}

    result = (True, [], None) if available else (False, conflicts, suggestion)
    checked_results[cache_key] = result
    return result
    # return (True, [], None) if available else (False, conflicts, suggestion)


@app.route("/check", methods=["POST"])
def check_availability():
    data = request.get_json() or {}
    room = data.get("room")
    start_time = data.get("start")
    end_time = data.get("end")

    if not all([room, start_time, end_time]):
        return jsonify({"error": "Missing parameters"}), 400

    # Parse and buffer the end time
    try:
        req_end = datetime.fromisoformat(end_time)
        fetch_end_dt = req_end + timedelta(minutes=30)
    except Exception as e:
        return jsonify({"error": f"Invalid datetime format: {str(e)}"}), 400

    # Get all related room calendar IDs
    rooms_to_check = get_rooms_to_check(room)
    calendar_ids = set()
    for r in rooms_to_check:
        cal_id = get_calendar_id_by_name(r)
        if cal_id:
            calendar_ids.add(cal_id)

    # Fetch events only until the needed time
    cached_events = batch_fetch_events_until(calendar_ids, fetch_end_dt)

    try:
        available, conflicts, suggestion = is_room_available_cached(room, start_time, end_time, cached_events, visited_rooms=None, checked_results={})
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

def classify_and_parse_query(query, memory_context):
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }

    today = datetime.now(pytz.timezone("Asia/Hong_Kong")).date().isoformat()
    system_prompt = f"""
You are an assistant that performs two tasks on the user's input:

1. Classify the intent of the user's query into one of these categories (reply ONLY the label in lowercase):
   - greeting
   - booking_query
   - unknown

2. If the intent is 'booking_query', extract meeting room booking info as a JSON array of objects, each with:
   - room: one of the exact valid room names (see list below)
   - start: ISO 8601 datetime with timezone
   - end: ISO 8601 datetime with timezone

If time of day is missing, assume the full day from 00:00 to 23:59 local time.

If the intent is not 'booking_query', return an empty JSON array.

The keyword 'today' in user input should be understood as the current date: {today}
Use the following prior context to help interpret ambiguous queries:
    {memory_context}
    
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

Respond ONLY in this exact format:

intent: <intent_label>
data: <JSON array>

Example:

intent: booking_query
data: [
  {{
    "room": "DI_Dream Room",
    "start": "2025-06-28T15:00:00+08:00",
    "end": "2025-06-28T16:00:00+08:00"
  }}
]

If the input is a greeting like "hello", respond:

intent: greeting
data: []
"""

    data = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": query}
        ],
        "temperature": 0.1
    }

    try:
        response = http_session.post(DEEPSEEK_API_URL, headers=headers, json=data)
        response.raise_for_status()
        content = response.json()['choices'][0]['message']['content'].strip()

        # Extract intent
        intent_match = re.search(r'^intent:\s*(\w+)', content, re.MULTILINE)
        data_match = re.search(r'data:\s*(\[.*\])', content, re.DOTALL)

        intent = intent_match.group(1).lower() if intent_match else "unknown"
        data_json = []

        if intent == "booking_query" and data_match:
            try:
                data_json = json.loads(data_match.group(1))
            except Exception:
                data_json = []
        elif intent == "unknown":
            data_json = ["error: unknown"]

        return intent, data_json

    except Exception as e:
        # API call failed - return unknown intent with error message string
        return "unknown", [f"error: unknown ({str(e)})"]



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
        response = http_session.post(DEEPSEEK_API_URL, headers=headers, json=data)
        response.raise_for_status()
        label = response.json()["choices"][0]["message"]["content"].strip().lower()
        return label
    except Exception as e:
        return "unknown"

def is_chinese(text):
    """Detect if the query contains Chinese characters."""
    return any('\u4e00' <= char <= '\u9fff' for char in text)

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
    
def batch_fetch_events_for_period(room_ids, start_iso, end_iso):
    """Fetch events from start_iso to end_iso for all rooms in parallel."""
    results = {}
    for cal_id in room_ids:
        try:
            response = query_events_with_retry(service, cal_id, start_iso, end_iso)
            results[cal_id] = response.get("items", [])
        except Exception:
            results[cal_id] = []
    return results

# -- Your existing /ask route, translation, parsing, greeting, etc remain unchanged --
@app.route("/ask", methods=["POST"])
def ask():
    timer = Timer()
    timer.mark("received_request")

    try:
        data = request.get_json()
        query = data.get("query", "").strip()
        if not query:
            return jsonify({"error": "Missing 'query' field"}), 400

        memory_context = ""
        if session.get("last_room"):
            memory_context += f"Previously mentioned room: {session['last_room']}\n"
        if session.get("last_start") and session.get("last_end"):
            memory_context += f"Previously mentioned time: from {session['last_start']} to {session['last_end']}\n"

        # Combined intent classification and parsing call (cached if needed)
        intent, parsed_list = classify_and_parse_query(query, memory_context=memory_context)
        timer.mark("after_classify_and_parse")

        query_is_chinese = is_chinese(query)

        if intent == "greeting":
            return jsonify(["Hello! How can I help you with meeting room availability today?"])

        if intent != "booking_query":
            msg = "Sorry, I can only help with meeting room availability queries."
            if query_is_chinese:
                msg = cached_translate_to_chinese(msg)
            return jsonify({"error": msg}), 400

        if isinstance(parsed_list, dict) and parsed_list.get("error"):
            error_msg = parsed_list["error"]
            if query_is_chinese:
                error_msg = cached_translate_to_chinese(error_msg)
            return jsonify({"error": error_msg}), 400

        # Ensure parsed_list is a list
        if not isinstance(parsed_list, list):
            parsed_list = [parsed_list]

        # Timezone and date setup
        tz = pytz.timezone("Asia/Hong_Kong")
        now = datetime.now(tz)
        start_of_today = datetime(now.year, now.month, now.day, 0, 0, 0, tzinfo=tz)

        max_end_dt = None
        for item in parsed_list:
            try:
                req_start = datetime.fromisoformat(item["start"])
                if req_start < start_of_today:
                    return jsonify(["Error: Start time must be today or later."])
                end_dt = datetime.fromisoformat(item["end"])
                if max_end_dt is None or end_dt > max_end_dt:
                    max_end_dt = end_dt
            except Exception as e:
                return jsonify({"error": f"Invalid datetime format in parsed data: {str(e)}"}), 400

        if max_end_dt is None:
            max_end_dt = start_of_today + timedelta(days=1)

        fetch_end_dt = max_end_dt + timedelta(minutes=30)

        # Collect all room calendar IDs for batch fetching
        all_rooms = set()
        for item in parsed_list:
            rooms_to_check = get_rooms_to_check(item["room"])
            all_rooms.update(rooms_to_check)

        calendar_ids = set()
        for room in all_rooms:
            cal_id = get_calendar_id_by_name(room)
            if cal_id:
                calendar_ids.add(cal_id)
                
        for item in parsed_list:
            if not item.get("room") and session.get("last_room"):
                item["room"] = session["last_room"]
            if not item.get("start") and session.get("last_start"):
                item["start"] = session["last_start"]
            if not item.get("end") and session.get("last_end"):
                item["end"] = session["last_end"]
                
        cached_events = {}
        if calendar_ids:
            cached_events = batch_fetch_events_for_period(calendar_ids, start_of_today.isoformat(), fetch_end_dt.isoformat())
        timer.mark("after_batch_fetch")

        checked_results = {}
        results = []
        for item in parsed_list:
            if not all(item.get(k) for k in ("room", "start", "end")):
                msg = "Missing room, start, or end time in parsed data"
                if query_is_chinese:
                    msg = cached_translate_to_chinese(msg)
                return jsonify({"error": msg}), 400

            session["last_room"] = item["room"]
            session["last_start"] = item["start"]
            session["last_end"] = item["end"]
            
            available, conflicts, suggestion = is_room_available_cached(
                item["room"],
                item["start"],
                item["end"],
                cached_events,
                visited_rooms=None,
                checked_results=checked_results
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
                result["suggestion"] = suggestion

            results.append(result)

        timer.mark("after_availability_check")

        response_data = json.dumps(results, ensure_ascii=False, indent=2)
        # if query_is_chinese:
        #     try:
        #         translated_response = cached_translate_to_chinese(response_data)
        #         timer.mark("after_response_translation")
        #         return Response(translated_response, mimetype="application/json")
        #     except Exception:
        #         pass

        timer.mark("before_response_return")
        print("Performance breakdown:\n" + timer.summary())
        sys.stdout.flush()
        return Response(response_data, mimetype="application/json")

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Unexpected error: {str(e)}"}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=4000, debug=True)
