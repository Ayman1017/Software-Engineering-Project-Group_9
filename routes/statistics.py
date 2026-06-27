from functools import wraps

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt, jwt_required
from sqlalchemy import func

from backend.models import City, Observation, WeatherStation, db

statistics_bp = Blueprint("statistics", __name__)


def government_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        claims = get_jwt()
        if claims.get("role") != "government":
            return jsonify({"error": "Government role required"}), 403
        return fn(*args, **kwargs)

    # Apply jwt_required so JWT is validated before the role check
    return jwt_required()(wrapper)


@statistics_bp.route("/statistics", methods=["GET"])
@government_required
def get_statistics():
    city_id = request.args.get("city_id", type=int)
    station_id = request.args.get("station_id")

    base_query = (
        db.session.query(
            func.avg(Observation.temperature).label("avg_temp"),
            func.min(Observation.temperature).label("min_temp"),
            func.max(Observation.temperature).label("max_temp"),
            func.stddev_samp(Observation.temperature).label("std_temp"),
            func.avg(Observation.humidity).label("avg_humidity"),
            func.min(Observation.humidity).label("min_humidity"),
            func.max(Observation.humidity).label("max_humidity"),
            func.stddev_samp(Observation.humidity).label("std_humidity"),
            func.avg(Observation.wind_speed).label("avg_wind"),
            func.count(Observation.id).label("total"),
        )
        .join(WeatherStation, Observation.station_id == WeatherStation.station_id)
    )

    if station_id:
        base_query = base_query.filter(Observation.station_id == station_id)
    elif city_id:
        base_query = base_query.filter(WeatherStation.city_id == city_id)

    row = base_query.one()

    def _r(val):
        return round(float(val), 2) if val is not None else None

    per_station_q = (
        db.session.query(
            WeatherStation.station_id,
            WeatherStation.name,
            City.city_name,
            func.avg(Observation.temperature).label("avg_temp"),
            func.avg(Observation.humidity).label("avg_hum"),
            func.avg(Observation.wind_speed).label("avg_wind"),
            func.count(Observation.id).label("count"),
        )
        .join(WeatherStation, Observation.station_id == WeatherStation.station_id)
        .join(City, WeatherStation.city_id == City.id)
        .group_by(WeatherStation.station_id, WeatherStation.name, City.city_name)
    )

    if station_id:
        per_station_q = per_station_q.filter(Observation.station_id == station_id)
    elif city_id:
        per_station_q = per_station_q.filter(WeatherStation.city_id == city_id)

    per_station = per_station_q.all()

    return jsonify({
        "temperature": {"avg": _r(row.avg_temp), "min": _r(row.min_temp), "max": _r(row.max_temp), "std": _r(row.std_temp)},
        "humidity": {"avg": _r(row.avg_humidity), "min": _r(row.min_humidity), "max": _r(row.max_humidity), "std": _r(row.std_humidity)},
        "wind_speed": {"avg": _r(row.avg_wind)},
        "total_observations": row.total,
        "per_station": [
            {
                "station_id": s.station_id,
                "name": s.name,
                "city": s.city_name,
                "avg_temperature": _r(s.avg_temp),
                "avg_humidity": _r(s.avg_hum),
                "avg_wind_speed": _r(s.avg_wind),
                "observation_count": s.count,
            }
            for s in per_station
        ],
    }), 200
