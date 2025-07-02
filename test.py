from datetime import datetime, timezone
import requests

access_token = "52f2cfa7a5bcdb94ac63611a94e1d0f74773b502"
org_slug = "dream-impact"
base_url = f"https://app.officernd.com/api/v2/organizations/{org_slug}"

headers = {
    "Authorization": f"Bearer {access_token}",
    "accept": "application/json"
}

def get_entity_names(endpoint):
    try:
        response = requests.get(f"{base_url}/{endpoint}", headers=headers)
        response.raise_for_status()
        data = response.json().get("data", [])
        return {entry["_id"]: entry.get("name", "Unknown") for entry in data}
    except Exception as e:
        print(f"Failed to get {endpoint}: {e}")
        return {}

def process_input(params):
    target_date = datetime(2025, 6, 23, 6, 30, tzinfo=timezone.utc)
    iso_date = target_date.strftime("%Y-%m-%dT%H:%M:%SZ")

    bookings_url = f"{base_url}/bookings"
    try:
        # Step 1: Fetch bookings
        response = requests.get(bookings_url, headers=headers, params={"seriesStart[$gte]": iso_date})
        response.raise_for_status()
        bookings = response.json().get("data", [])

        # Step 2: Collect all unique location and resource IDs
        location_ids = {b.get("location") for b in bookings if b.get("location")}
        resource_ids = {b.get("resource") for b in bookings if b.get("resource")}

        # Step 3: Get names
        location_names = get_entity_names("locations")
        resource_names = get_entity_names("resources")

        # Step 4: Enrich bookings with names
        for b in bookings:
            b["locationName"] = location_names.get(b.get("location"), "Unknown Location")
            b["resourceName"] = resource_names.get(b.get("resource"), "Unknown Resource")

        return bookings

    except requests.exceptions.HTTPError as e:
        return {
            "_error": {
                "message": f"API request failed: {e.response.status_code}",
                "details": {
                    "url": e.response.url,
                    "reason": e.response.reason,
                    "response_text": e.response.text[:200]
                }
            }
        }
    except Exception as e:
        return {"_error": {"message": f"Unknown error: {str(e)}"}}

# Example call
if __name__ == "__main__":
    from pprint import pprint
    pprint(process_input(None))
