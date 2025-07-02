
from flask import Flask, request, jsonify
import requests
import os

app = Flask(__name__)

# Replace with your actual OfficeRnD API token and org ID
OFFICERND_API_KEY = 'your_officernd_api_key'
ORG_ID = 'your_organization_id'
API_BASE = 'https://api.officernd.com/v1'

HEADERS = {
    'Authorization': f'Bearer {OFFICERND_API_KEY}',
    'Content-Type': 'application/json'
}

@app.route('/check_availability', methods=['GET'])
def check_availability():
    room_id = request.args.get('roomId')
    start = request.args.get('start')
    end = request.args.get('end')

    if not all([room_id, start, end]):
        return jsonify({'error': 'Missing parameters'}), 400

    url = f"{API_BASE}/bookings/availability"
    params = {
        'resourceId': room_id,
        'start': start,
        'end': end,
        'organizationId': ORG_ID
    }

    response = requests.get(url, headers=HEADERS, params=params)
    return jsonify(response.json()), response.status_code

@app.route('/create_booking', methods=['POST'])
def create_booking():
    data = request.json
    room_id = data.get('roomId')
    start = data.get('start')
    end = data.get('end')
    user_id = data.get('userId')

    if not all([room_id, start, end, user_id]):
        return jsonify({'error': 'Missing fields'}), 400

    url = f"{API_BASE}/bookings"
    payload = {
        'resourceId': room_id,
        'start': start,
        'end': end,
        'userId': user_id
    }

    response = requests.post(url, headers=HEADERS, json=payload)
    return jsonify(response.json()), response.status_code

if __name__ == '__main__':
    app.run(debug=True)
