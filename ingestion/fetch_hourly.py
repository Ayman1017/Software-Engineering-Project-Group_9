import os
from datetime import date, datetime, timedelta, timezone

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


def _safe_float(value) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)
        return None if f != f else f  # NaN guard
    except (TypeError, ValueError):
        return None


def _safe_int(value) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_utc(ts_str: str) -> datetime | None:
    """Parse a Meteostat timestamp string to a timezone-aware UTC datetime."""
    if not ts_str:
        return None
    try:
        if ts_str.endswith("Z"):
            return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        # Some responses omit timezone — treat as UTC
        dt = datetime.fromisoformat(ts_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def fetch_hourly_data(
    station_id: str,
    start: date,
    end: date,
) -> list[dict]:
    """
    Fetch and clean hourly observations for *station_id* between *start* and *end*.

    Handles:
    - Missing / NaN values → None
    - Duplicate timestamps → de-duplicated (first seen wins)
    - Timezone awareness → all timestamps in UTC
    - Records with no temperature *and* no humidity → dropped
    """
    url = f"{BASE_URL}/stations/hourly"
    params = {
        "station": station_id,
        "start": start.strftime("%Y-%m-%d"),
        "end": end.strftime("%Y-%m-%d"),
        "units": "metric",
        "timezone": "UTC",
        "model": "1",  # use model-filled data to reduce gaps
    }

    resp = requests.get(url, headers=HEADERS, params=params, timeout=30)
    print(f"[debug] stations/hourly ({station_id}) HTTP {resp.status_code}: {resp.text[:300]}")
    resp.raise_for_status()

    raw_records: list[dict] = resp.json().get("data", [])
    cleaned: list[dict] = []
    seen: set[datetime] = set()

    for record in raw_records:
        ts = _parse_utc(record.get("time", ""))
        if ts is None or ts in seen:
            continue
        seen.add(ts)

        temp = _safe_float(record.get("temp"))
        humidity = _safe_float(record.get("rhum"))
        wind_speed = _safe_float(record.get("wspd"))
        condition_code = _safe_int(record.get("coco"))

        if temp is None and humidity is None:
            continue

        cleaned.append({
            "station_id": station_id,
            "obs_timestamp": ts,
            "temperature": temp,
            "humidity": humidity,
            "wind_speed": wind_speed,
            "condition_code": condition_code,
        })

    return cleaned


def fetch_recent_hourly(station_id: str, days_back: int = 7) -> list[dict]:
    """Convenience wrapper: fetch the last *days_back* days for a station."""
    end = date.today()
    start = end - timedelta(days=days_back)
    return fetch_hourly_data(station_id, start, end)
