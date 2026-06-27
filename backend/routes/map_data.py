from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required
from sqlalchemy import func

from backend.models import City, Observation, WeatherStation, db

map_data_bp = Blueprint("map_data", __name__)


@map_data_bp.route("/map_data", methods=["GET"])
@jwt_required()
def get_map_data():
    city_id = request.args.get("city_id", type=int)

    # Subquery: most recent observation timestamp per station
    latest_sq = (
        db.session.query(
            Observation.station_id,
            func.max(Observation.obs_timestamp).label("max_ts"),
        )
        .group_by(Observation.station_id)
        .subquery()
    )

    query = (
        db.session.query(WeatherStation, Observation, City)
        .join(City, WeatherStation.city_id == City.id)
        .outerjoin(latest_sq, WeatherStation.station_id == latest_sq.c.station_id)
        .outerjoin(
            Observation,
            (Observation.station_id == latest_sq.c.station_id)
            & (Observation.obs_timestamp == latest_sq.c.max_ts),
        )
    )

    if city_id:
        query = query.filter(WeatherStation.city_id == city_id)

    rows = query.all()

    features = []
    for station, obs, city in rows:
        temp = obs.temperature if obs else None
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [station.longitude, station.latitude],
            },
            "properties": {
                "station_id": station.station_id,
                "name": station.name,
                "city": city.city_name,
                "elevation": station.elevation,
                "temperature": temp,
                "humidity": obs.humidity if obs else None,
                "wind_speed": obs.wind_speed if obs else None,
                "condition_code": obs.condition_code if obs else None,
                "last_updated": obs.obs_timestamp.isoformat() if obs else None,
            },
        })

    return jsonify({"type": "FeatureCollection", "features": features}), 200
