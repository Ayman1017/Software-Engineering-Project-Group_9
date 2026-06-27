from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required

from backend.models import City, WeatherStation

stations_bp = Blueprint("stations", __name__)


@stations_bp.route("/stations", methods=["GET"])
@jwt_required()
def get_stations():
    city_id   = request.args.get("city_id", type=int)
    city_name = request.args.get("city_name", type=str)

    query = WeatherStation.query.join(City)

    if city_id:
        query = query.filter(WeatherStation.city_id == city_id)
    elif city_name:
        query = query.filter(City.city_name.ilike(f"%{city_name}%"))

    stations = query.order_by(WeatherStation.name).all()

    return jsonify([
        {
            "station_id":   s.station_id,
            "station_name": s.name,
            "name":         s.name,
            "latitude":     s.latitude,
            "longitude":    s.longitude,
            "elevation":    s.elevation,
            "city_id":      s.city_id,
            "city_name":    s.city.city_name if s.city else None,
        }
        for s in stations
    ]), 200
