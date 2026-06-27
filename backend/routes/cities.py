from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required

from backend.models import City

cities_bp = Blueprint("cities", __name__)


@cities_bp.route("/cities", methods=["GET"])
@jwt_required()
def get_cities():
    cities = City.query.order_by(City.city_name).all()
    return jsonify([c.to_dict() for c in cities]), 200
