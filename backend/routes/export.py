import csv
import io
from datetime import datetime

from flask import Blueprint, Response, request
from flask_jwt_extended import jwt_required

from backend.models import City, Observation, WeatherStation

export_bp = Blueprint("export", __name__)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


@export_bp.route("/export_csv", methods=["GET"])
@jwt_required()
def export_csv():
    station_id = request.args.get("station_id")
    city_id = request.args.get("city_id", type=int)
    start = _parse_dt(request.args.get("start"))
    end = _parse_dt(request.args.get("end"))

    query = (
        Observation.query
        .join(WeatherStation, Observation.station_id == WeatherStation.station_id)
        .join(City, WeatherStation.city_id == City.id)
    )

    if station_id:
        query = query.filter(Observation.station_id == station_id)
    if city_id:
        query = query.filter(WeatherStation.city_id == city_id)
    if start:
        query = query.filter(Observation.obs_timestamp >= start)
    if end:
        query = query.filter(Observation.obs_timestamp <= end)

    observations = query.order_by(Observation.obs_timestamp.asc()).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "observation_id",
        "station_id",
        "station_name",
        "city",
        "country_code",
        "obs_timestamp_utc",
        "temperature_C",
        "humidity_pct",
        "wind_speed_ms",
        "condition_code",
    ])

    for o in observations:
        writer.writerow([
            o.id,
            o.station_id,
            o.station.name,
            o.station.city.city_name,
            o.station.city.country_code,
            o.obs_timestamp.isoformat(),
            o.temperature,
            o.humidity,
            o.wind_speed,
            o.condition_code,
        ])

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=meteocity_export.csv"},
    )
