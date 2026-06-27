"""
MeteoCity data ingestion entry-point.

Usage (from project root):
    python -m backend.ingestion.ingest
    python -m backend.ingestion.ingest --days 30

When RAPIDAPI_KEY is not set (or is the placeholder), the script
automatically generates realistic mock data so the database can be
populated for development and testing without a live API key.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from datetime import datetime, timedelta, timezone

import numpy as np
from dotenv import load_dotenv
from geoalchemy2.elements import WKTElement
from sqlalchemy.dialects.postgresql import insert as pg_insert

from backend.app import create_app
from backend.models import City, DataVariable, Observation, WeatherStation, db

load_dotenv()

# ─── Mock station definitions ──────────────────────────────────────────────────

MOCK_STATIONS: dict[str, list[dict]] = {
    "Milan": [
        {
            "id": "MILAN_MXP",
            "name": "Milano Malpensa Airport",
            "lat": 45.6306,
            "lon": 8.7231,
            "elevation": 234.0,
            "country_code": "IT",
            "temp_min": 14.0,
            "temp_max": 34.0,
        },
        {
            "id": "MILAN_LIN",
            "name": "Milano Linate Airport",
            "lat": 45.4453,
            "lon": 9.2767,
            "elevation": 103.0,
            "country_code": "IT",
            "temp_min": 15.0,
            "temp_max": 35.0,
        },
        {
            "id": "MILAN_CTR",
            "name": "Milano City Centre",
            "lat": 45.4654,
            "lon": 9.1859,
            "elevation": 122.0,
            "country_code": "IT",
            "temp_min": 16.0,
            "temp_max": 36.0,
        },
    ],
    "Rome": [
        {
            "id": "ROME_FCO",
            "name": "Roma Fiumicino Airport",
            "lat": 41.8003,
            "lon": 12.2389,
            "elevation": 3.0,
            "country_code": "IT",
            "temp_min": 18.0,
            "temp_max": 36.0,
        },
        {
            "id": "ROME_CIA",
            "name": "Roma Ciampino Airport",
            "lat": 41.7994,
            "lon": 12.5949,
            "elevation": 130.0,
            "country_code": "IT",
            "temp_min": 17.0,
            "temp_max": 35.0,
        },
        {
            "id": "ROME_CTR",
            "name": "Roma City Centre",
            "lat": 41.9028,
            "lon": 12.4964,
            "elevation": 21.0,
            "country_code": "IT",
            "temp_min": 19.0,
            "temp_max": 38.0,
        },
    ],
}

# WMO condition codes weighted toward clear/fair for a Mediterranean summer
_CONDITION_CODES = [1, 2, 3, 4, 5, 21, 61]
_CONDITION_WEIGHTS = [0.28, 0.28, 0.18, 0.12, 0.05, 0.05, 0.04]


# ─── Mock data generator ───────────────────────────────────────────────────────

def generate_mock_observations(
    station_id: str,
    temp_min: float,
    temp_max: float,
    days: int = 30,
    hum_min: float = 40.0,
    hum_max: float = 80.0,
    start_date=None,
) -> list[dict]:
    """
    Generate hourly mock observations for *days* days.

    Temperature follows a realistic sinusoidal daily cycle (peak ~14:00 UTC,
    trough ~05:00 UTC) with day-to-day drift.  Humidity is inversely
    correlated with temperature.
    """
    rng = np.random.default_rng(seed=abs(hash(station_id)) % (2 ** 31))

    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    if start_date is not None:
        start = datetime(start_date.year, start_date.month, start_date.day, 0, 0, tzinfo=timezone.utc)
    else:
        start = now - timedelta(days=days)
    hours = days * 24

    timestamps = [start + timedelta(hours=h) for h in range(hours)]
    hour_of_day = np.array([ts.hour for ts in timestamps], dtype=float)

    # Day-to-day drift (random walk, capped)
    daily_drift = np.cumsum(rng.normal(0, 0.6, days))
    daily_drift -= daily_drift.mean()
    daily_drift = np.clip(daily_drift, -4, 4)
    drift_hourly = np.repeat(daily_drift, 24)[:hours]

    # Sinusoidal daily cycle: amplitude = ¼ of the full range
    amplitude = (temp_max - temp_min) / 4.0
    daily_cycle = amplitude * np.sin((hour_of_day - 5.0) * np.pi / 12.0)

    temp_base = (temp_min + temp_max) / 2.0
    temperatures = temp_base + daily_cycle + drift_hourly + rng.normal(0, 0.4, hours)
    temperatures = np.round(np.clip(temperatures, temp_min - 1, temp_max + 1), 1)

    # Humidity: inversely correlated with temperature + small noise
    t_norm = (temperatures - temperatures.min()) / (temperatures.max() - temperatures.min() + 1e-9)
    humidity = hum_max - t_norm * (hum_max - hum_min) + rng.normal(0, 2.5, hours)
    humidity = np.round(np.clip(humidity, hum_min, hum_max), 1)

    # Wind speed: half-normal distribution, occasional gusts
    wind_speed = np.abs(rng.normal(3.5, 2.5, hours))
    wind_speed = np.round(np.clip(wind_speed, 0.0, 18.0), 1)

    # Condition codes
    condition_codes = rng.choice(_CONDITION_CODES, size=hours, p=_CONDITION_WEIGHTS)

    return [
        {
            "station_id": station_id,
            "obs_timestamp": timestamps[i],
            "temperature": float(temperatures[i]),
            "humidity": float(humidity[i]),
            "wind_speed": float(wind_speed[i]),
            "condition_code": int(condition_codes[i]),
        }
        for i in range(hours)
    ]


# ─── Seed helpers ──────────────────────────────────────────────────────────────

def seed_data_variables() -> None:
    """Insert canonical variable definitions once."""
    defaults = [
        ("temperature", "°C",   "Air temperature at 2 m above ground"),
        ("humidity",    "%",    "Relative humidity"),
        ("wind_speed",  "m/s",  "Wind speed at 10 m above ground"),
        ("condition_code", "-", "WMO weather condition code"),
    ]
    for name, unit, desc in defaults:
        if not DataVariable.query.filter_by(variable_name=name).first():
            db.session.add(DataVariable(variable_name=name, unit=unit, description=desc))
    db.session.commit()
    print("[ingest] Data variables seeded.")


# ─── Upsert helpers ────────────────────────────────────────────────────────────

def upsert_city(city_name: str, country_code: str) -> City:
    city = City.query.filter_by(city_name=city_name).first()
    if not city:
        city = City(city_name=city_name, country_code=country_code)
        db.session.add(city)
        db.session.commit()
        print(f"  [ingest] Created city: {city_name}")
    return city


def upsert_mock_station(s: dict, city: City) -> WeatherStation:
    wkt = WKTElement(f"POINT({s['lon']} {s['lat']})", srid=4326)
    station = db.session.get(WeatherStation, s["id"])
    if not station:
        station = WeatherStation(
            station_id=s["id"],
            name=s["name"],
            latitude=s["lat"],
            longitude=s["lon"],
            elevation=s["elevation"],
            location=wkt,
            city_id=city.id,
        )
        db.session.add(station)
    else:
        station.name = s["name"]
        station.latitude = s["lat"]
        station.longitude = s["lon"]
        station.elevation = s["elevation"]
        station.location = wkt
    db.session.commit()
    return station


def bulk_upsert_observations(records: list[dict]) -> int:
    """
    Insert observations, silently skipping duplicates via ON CONFLICT DO NOTHING.
    Returns the number of rows actually inserted.
    """
    if not records:
        return 0

    rows = [
        {
            "station_id":    r["station_id"],
            "obs_timestamp": r["obs_timestamp"],
            "temperature":   r["temperature"],
            "humidity":      r["humidity"],
            "wind_speed":    r["wind_speed"],
            "condition_code": r["condition_code"],
        }
        for r in records
    ]

    stmt = pg_insert(Observation).values(rows).on_conflict_do_nothing(
        constraint="uq_station_timestamp"
    )
    result = db.session.execute(stmt)
    db.session.commit()
    return result.rowcount or 0


# ─── Main ingestion routine ────────────────────────────────────────────────────

def run_ingestion(days_back: int = 30) -> None:
    rapidapi_key = os.getenv("RAPIDAPI_KEY", "")
    use_mock = not rapidapi_key or rapidapi_key == "your-rapidapi-key-here"

    app = create_app()

    with app.app_context():
        print("[ingest] Ensuring database schema …")
        db.create_all()

        seed_data_variables()

        if use_mock:
            print(
                f"\n[ingest] RAPIDAPI_KEY not set — running in MOCK MODE.\n"
                f"         Generating {days_back} days × 24 h of synthetic data "
                f"for {sum(len(v) for v in MOCK_STATIONS.values())} stations.\n"
            )
            _run_mock_ingestion(days_back)
        else:
            try:
                _run_live_ingestion(days_back)
            except Exception as exc:
                print(f"\n[ingest] WARNING: Live ingestion failed ({exc}). Falling back to MOCK MODE.\n")
                _run_mock_ingestion(days_back)


def _run_mock_ingestion(days_back: int) -> None:
    """Generate and insert synthetic observations for all mock stations."""
    total_inserted = 0

    for city_name, stations in MOCK_STATIONS.items():
        country_code = stations[0]["country_code"]
        city = upsert_city(city_name, country_code)

        for s in stations:
            print(f"[ingest] Station {s['id']}  ({s['name']}, {city_name})")
            upsert_mock_station(s, city)

            records = generate_mock_observations(
                station_id=s["id"],
                temp_min=s["temp_min"],
                temp_max=s["temp_max"],
                days=days_back,
            )

            inserted = bulk_upsert_observations(records)
            total_inserted += inserted
            print(f"         {len(records)} records generated, {inserted} new rows inserted.")

    print(f"\n[ingest] Done. Total new observations inserted: {total_inserted}")


def _run_live_ingestion(days_back: int) -> None:
    """Fetch real data from the Meteostat RapidAPI (requires valid RAPIDAPI_KEY)."""
    print(f"[debug] _run_live_ingestion() entered, days_back={days_back}")
    _dbg_key = os.getenv("RAPIDAPI_KEY", "")
    print(f"[debug] RAPIDAPI_KEY first 10 chars: {repr(_dbg_key[:10])!s} (total len={len(_dbg_key)})")

    from datetime import date, timedelta
    from backend.ingestion.fetch_hourly import fetch_hourly_data
    from backend.ingestion.fetch_stations import TARGET_CITIES, get_stations_for_all_cities

    print(f"\n[ingest] LIVE MODE — fetching station list …")
    all_stations = get_stations_for_all_cities()
    print(f"[debug] get_stations_for_all_cities() returned: type={type(all_stations)}, value={all_stations!r}")

    if not all_stations:
        raise RuntimeError("No stations returned from API — invalid or quota-exceeded RAPIDAPI_KEY.")

    fetch_end = date.today()
    fetch_start = fetch_end - timedelta(days=days_back)
    total_inserted = 0

    for station_data in all_stations:
        city_name    = station_data["_city_name"]
        country_code = station_data["_country_code"]
        station_id   = station_data.get("id", "")
        if not station_id:
            continue

        print(f"\n[ingest] Station {station_id}  ({city_name})")
        city    = upsert_city(city_name, country_code)

        loc  = station_data.get("location", {})
        lat  = float(loc.get("latitude",  0))
        lon  = float(loc.get("longitude", 0))
        elev = loc.get("elevation")
        name_raw = station_data.get("name", station_id)
        name = (
            name_raw.get("en") or next(iter(name_raw.values()), station_id)
            if isinstance(name_raw, dict)
            else str(name_raw)
        )
        mock_s = {
            "id": station_id, "name": name,
            "lat": lat, "lon": lon,
            "elevation": float(elev) if elev is not None else None,
        }
        upsert_mock_station(mock_s, city)

        print(f"  Fetching hourly: {fetch_start} → {fetch_end} …")
        try:
            records = fetch_hourly_data(station_id, fetch_start, fetch_end)
        except Exception as exc:
            print(f"  WARNING: fetch failed: {exc}")
            continue

        inserted = bulk_upsert_observations(records)
        total_inserted += inserted
        print(f"  {len(records)} records fetched, {inserted} new rows inserted.")

    print(f"\n[ingest] Done. Total new observations inserted: {total_inserted}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MeteoCity ingestion script")
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="Number of past days to generate/fetch (default: 30)",
    )
    args = parser.parse_args()
    run_ingestion(days_back=args.days)
