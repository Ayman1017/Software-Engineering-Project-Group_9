import os
import sys

# Allow `python backend/app.py` to resolve `from backend.X` imports
_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from flask import Flask, jsonify
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from flask_migrate import Migrate

from backend.config import config_by_name
from backend.models import db, revoked_tokens

jwt = JWTManager()
migrate = Migrate()


def create_app(config_name: str = None) -> Flask:
    if config_name is None:
        config_name = os.getenv("FLASK_ENV", "default")

    app = Flask(__name__)
    app.config.from_object(config_by_name[config_name])

    CORS(app)
    db.init_app(app)
    jwt.init_app(app)
    migrate.init_app(app, db)

    @jwt.token_in_blocklist_loader
    def check_if_revoked(jwt_header, jwt_payload):
        return jwt_payload["jti"] in revoked_tokens

    @jwt.revoked_token_loader
    def revoked_callback(jwt_header, jwt_payload):
        return jsonify({"error": "Token has been revoked. Please log in again."}), 401

    @jwt.expired_token_loader
    def expired_callback(jwt_header, jwt_payload):
        return jsonify({"error": "Token has expired. Please log in again."}), 401

    @jwt.unauthorized_loader
    def missing_token_callback(error):
        return jsonify({"error": "Authorization token required."}), 401

    @jwt.invalid_token_loader
    def invalid_token_callback(error):
        return jsonify({"error": "Invalid token."}), 422

    # Blueprints — imported here to avoid circular imports at module level
    from backend.routes.auth import auth_bp
    from backend.routes.cities import cities_bp
    from backend.routes.export import export_bp
    from backend.routes.ingest_routes import ingest_bp
    from backend.routes.map_data import map_data_bp
    from backend.routes.observations import observations_bp
    from backend.routes.stations import stations_bp
    from backend.routes.statistics import statistics_bp

    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(cities_bp, url_prefix="/api")
    app.register_blueprint(stations_bp, url_prefix="/api")
    app.register_blueprint(observations_bp, url_prefix="/api")
    app.register_blueprint(statistics_bp, url_prefix="/api")
    app.register_blueprint(map_data_bp, url_prefix="/api")
    app.register_blueprint(export_bp, url_prefix="/api")
    app.register_blueprint(ingest_bp, url_prefix="/ingest")

    @app.route("/health")
    def health():
        return jsonify({"status": "ok"})

    return app


if __name__ == "__main__":
    app = create_app()
    with app.app_context():
        db.create_all()
    app.run(host="0.0.0.0", port=5000)
