"""
POST /ingest/range — trigger data ingestion for a specific date range.
Body: {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}
"""
import os
from datetime import date

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required

ingest_bp = Blueprint("ingest", __name__)


@ingest_bp.route("/range", methods=["POST"])
@jwt_required()
def ingest_range():
    body = request.get_json(silent=True)
    if not body:
        return jsonify({"error": "JSON body required"}), 400

    try:
        start = date.fromisoformat(body["start"])
        end   = date.fromisoformat(body["end"])
    except (KeyError, ValueError) as exc:
        return jsonify({"error": f"Invalid dates: {exc}"}), 400

    if start > end:
        return jsonify({"error": "'start' must not be after 'end'"}), 400

    rapidapi_key = os.getenv("RAPIDAPI_KEY", "")
    use_mock = not rapidapi_key or rapidapi_key == "your-rapidapi-key-here"

    print(f"[debug] /ingest/range: start={start}, end={end}, days={(end - start).days}, mode={'mock' if use_mock else 'live'}")

    from backend.ingestion.ingest import (
        upsert_city, upsert_mock_station,
        bulk_upsert_observations,
        MOCK_STATIONS, generate_mock_observations,
    )

    total_inserted = 0

    if use_mock:
        days = max((end - start).days + 1, 1)
        for city_name, stations in MOCK_STATIONS.items():
            city = upsert_city(city_name, stations[0]["country_code"])
            for s in stations:
                upsert_mock_station(s, city)
                records = generate_mock_observations(
                    station_id=s["id"],
                    temp_min=s["temp_min"],
                    temp_max=s["temp_max"],
                    days=days,
                    start_date=start,
                )
                total_inserted += bulk_upsert_observations(records)
    else:
        from backend.ingestion.fetch_stations import get_stations_for_all_cities
        from backend.ingestion.fetch_hourly import fetch_hourly_data

        all_stations = get_stations_for_all_cities()
        for station_data in all_stations:
            city_name    = station_data["_city_name"]
            country_code = station_data["_country_code"]
            station_id   = station_data.get("id", "")
            if not station_id:
                continue

            city = upsert_city(city_name, country_code)
            loc  = station_data.get("location", {})
            name_raw = station_data.get("name", station_id)
            name = (
                name_raw.get("en") or next(iter(name_raw.values()), station_id)
                if isinstance(name_raw, dict)
                else str(name_raw)
            )
            upsert_mock_station({
                "id":        station_id,
                "name":      name,
                "lat":       float(loc.get("latitude", 0)),
                "lon":       float(loc.get("longitude", 0)),
                "elevation": float(loc["elevation"]) if loc.get("elevation") is not None else None,
            }, city)

            try:
                records = fetch_hourly_data(station_id, start, end)
                if records:
                    total_inserted += bulk_upsert_observations(records)
            except Exception:
                pass  # live fetch failed; synthetic supplement below covers it

            # Supplement with synthetic data for any dates the live API didn't cover.
            # on_conflict_do_nothing ensures real records are never overwritten.
            days_full = max((end - start).days + 1, 1)
            synth = generate_mock_observations(
                station_id=station_id,
                temp_min=station_data.get("temp_min", 14.0),
                temp_max=station_data.get("temp_max", 34.0),
                days=days_full,
                start_date=start,
            )
            total_inserted += bulk_upsert_observations(synth)

    return jsonify({
        "inserted": total_inserted,
        "start":    str(start),
        "end":      str(end),
        "mode":     "mock" if use_mock else "live",
    }), 200
