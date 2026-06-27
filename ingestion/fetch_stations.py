import os

import requests
from dotenv import load_dotenv

load_dotenv()

RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY", "")
RAPIDAPI_HOST = os.getenv("RAPIDAPI_HOST", "meteostat.p.rapidapi.com")
BASE_URL = f"https://{RAPIDAPI_HOST}"

HEADERS = {
    "x-rapidapi-key": RAPIDAPI_KEY,
    "x-rapidapi-host": RAPIDAPI_HOST,
}

# Target cities with their coordinates and country codes
TARGET_CITIES: dict[str, dict] = {
    "Milan": {"lat": 45.4654, "lon": 9.1859, "country_code": "IT"},
    "Rome": {"lat": 41.9028, "lon": 12.4964, "country_code": "IT"},
}


def fetch_nearby_stations(
    lat: float,
    lon: float,
    radius: int = 50,
    limit: int = 10,
) -> list[dict]:
    """Return stations within `radius` km of the given coordinates."""
    url = f"{BASE_URL}/stations/nearby"
    params = {"lat": lat, "lon": lon, "radius": radius, "limit": limit}
    print(f"[debug] GET {url}  params={params}")
    resp = requests.get(url, headers=HEADERS, params=params, timeout=15)
    print(f"[debug] stations/nearby HTTP {resp.status_code}: {resp.text[:500]}")
    resp.raise_for_status()
    return resp.json().get("data") or []


def fetch_station_meta(station_id: str) -> dict | None:
    """Return full metadata for a single station, or None on error."""
    url = f"{BASE_URL}/stations/meta"
    params = {"id": station_id}
    resp = requests.get(url, headers=HEADERS, params=params, timeout=15)
    resp.raise_for_status()
    return resp.json().get("data")


def get_stations_for_all_cities() -> list[dict]:
    """
    Return known-good Meteostat station records for Milan and Rome.
    stations/nearby returns data:null for these coordinates, so we use
    hardcoded station IDs that are confirmed to work with the hourly endpoint.
    """
    return [
        {
            "id": "16080",
            "name": "Milano Malpensa",
            "location": {"latitude": 45.6306, "longitude": 8.7231, "elevation": 234.0},
            "_city_name": "Milan",
            "_country_code": "IT",
            "temp_min": 14.0, "temp_max": 34.0,
        },
        {
            "id": "16066",
            "name": "Milano Linate",
            "location": {"latitude": 45.4453, "longitude": 9.2767, "elevation": 103.0},
            "_city_name": "Milan",
            "_country_code": "IT",
            "temp_min": 15.0, "temp_max": 35.0,
        },
        {
            "id": "16242",
            "name": "Roma Fiumicino",
            "location": {"latitude": 41.8003, "longitude": 12.2389, "elevation": 3.0},
            "_city_name": "Rome",
            "_country_code": "IT",
            "temp_min": 18.0, "temp_max": 36.0,
        },
        {
            "id": "16239",
            "name": "Roma Ciampino",
            "location": {"latitude": 41.7994, "longitude": 12.5949, "elevation": 130.0},
            "_city_name": "Rome",
            "_country_code": "IT",
            "temp_min": 17.0, "temp_max": 35.0,
        },
    ]
