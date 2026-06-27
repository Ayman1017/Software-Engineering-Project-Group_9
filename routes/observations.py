from datetime import datetime, timedelta
from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required
from sqlalchemy.orm import joinedload

from backend.models import City, DataVariable, Observation, WeatherStation

observations_bp = Blueprint("observations", __name__)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


@observations_bp.route("/observations", methods=["GET"])
@jwt_required()
def get_observations():
    station_id = request.args.get("station_id")
    city_id    = request.args.get("city_id", type=int)
    city_name  = request.args.get("city")          # new: "milan" / "rome"
    start      = _parse_dt(request.args.get("start"))
    end        = _parse_dt(request.args.get("end"))
    limit      = min(request.args.get("limit", 100, type=int), 1000)
    offset     = request.args.get("offset", 0, type=int)

    # Resolve city name → city_id when provided as a string
    if city_name and not city_id:
        city_row = City.query.filter(
            City.city_name.ilike(f"%{city_name.strip()}%")
        ).first()
        if city_row:
            city_id = city_row.id

    query = (
        Observation.query
        .options(joinedload(Observation.station))
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

    total = query.count()
    obs = (
        query.order_by(Observation.obs_timestamp.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return jsonify({
        "total":  total,
        "offset": offset,
        "limit":  limit,
        "observations": [
            {
                **o.to_dict(),
                "station_name": o.station.name if o.station else o.station_id,
                "is_synthetic": o.condition_code in {1, 2, 3, 4, 5, 21, 61},
            }
            for o in obs
        ],
    }), 200


@observations_bp.route("/trend_data", methods=["GET"])
@jwt_required()
def get_trend_data():
    station_id = request.args.get("station_id")
    city_id    = request.args.get("city_id", type=int)
    variable   = request.args.get("variable", "temperature")
    start      = _parse_dt(request.args.get("start"))
    end        = _parse_dt(request.args.get("end"))

    allowed = {"temperature", "humidity", "wind_speed"}
    if variable not in allowed:
        return jsonify({"error": f"variable must be one of {sorted(allowed)}"}), 400

    query = (
        Observation.query
        .options(joinedload(Observation.station))
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

    obs = query.order_by(Observation.obs_timestamp.asc()).all()

    data = [
        {
            "timestamp":    o.obs_timestamp.isoformat(),
            "value":        getattr(o, variable),
            "station_id":   o.station_id,
            "station_name": o.station.name if o.station else o.station_id,
        }
        for o in obs
        if getattr(o, variable) is not None
    ]

    return jsonify({"variable": variable, "data": data}), 200


@observations_bp.route("/variables", methods=["GET"])
@jwt_required()
def get_variables():
    variables = DataVariable.query.order_by(DataVariable.variable_name).all()
    return jsonify([v.to_dict() for v in variables]), 200
