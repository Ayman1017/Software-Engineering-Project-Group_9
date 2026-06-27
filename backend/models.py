from datetime import datetime, timezone

import bcrypt
from flask_sqlalchemy import SQLAlchemy
from geoalchemy2 import Geometry
from sqlalchemy import Index, UniqueConstraint

db = SQLAlchemy()

# In-memory JWT blocklist. Replace with Redis in production.
revoked_tokens: set = set()


class User(db.Model):
    __tablename__ = "users"

    __table_args__ = (
        db.CheckConstraint(
            "role IN ('student', 'researcher', 'ngo', 'government', 'user')",
            name="users_role_check",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="user")
    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    def set_password(self, password: str) -> None:
        self.password_hash = bcrypt.hashpw(
            password.encode("utf-8"), bcrypt.gensalt()
        ).decode("utf-8")

    def check_password(self, password: str) -> bool:
        return bcrypt.checkpw(
            password.encode("utf-8"), self.password_hash.encode("utf-8")
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "username": self.username,
            "role": self.role,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class City(db.Model):
    __tablename__ = "cities"

    id = db.Column(db.Integer, primary_key=True)
    city_name = db.Column(db.String(100), nullable=False)
    country_code = db.Column(db.String(3), nullable=False)

    stations = db.relationship("WeatherStation", backref="city", lazy="dynamic")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "city_name": self.city_name,
            "country_code": self.country_code,
        }


class WeatherStation(db.Model):
    __tablename__ = "weather_stations"

    station_id = db.Column(db.String(20), primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    latitude = db.Column(db.Float, nullable=False)
    longitude = db.Column(db.Float, nullable=False)
    elevation = db.Column(db.Float)
    location = db.Column(Geometry(geometry_type="POINT", srid=4326))
    city_id = db.Column(db.Integer, db.ForeignKey("cities.id"), nullable=False)

    observations = db.relationship("Observation", backref="station", lazy="dynamic")

    def to_dict(self) -> dict:
        return {
            "station_id": self.station_id,
            "name": self.name,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "elevation": self.elevation,
            "city_id": self.city_id,
            "city_name": self.city.city_name if self.city else None,
        }


class Observation(db.Model):
    __tablename__ = "observations"

    id = db.Column(db.Integer, primary_key=True)
    station_id = db.Column(
        db.String(20),
        db.ForeignKey("weather_stations.station_id"),
        nullable=False,
    )
    obs_timestamp = db.Column(db.DateTime(timezone=True), nullable=False)
    temperature = db.Column(db.Float)
    humidity = db.Column(db.Float)
    wind_speed = db.Column(db.Float)
    condition_code = db.Column(db.Integer)

    __table_args__ = (
        UniqueConstraint("station_id", "obs_timestamp", name="uq_station_timestamp"),
        Index("ix_obs_station_time", "station_id", "obs_timestamp"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "station_id": self.station_id,
            "obs_timestamp": self.obs_timestamp.isoformat(),
            "temperature": self.temperature,
            "humidity": self.humidity,
            "wind_speed": self.wind_speed,
            "condition_code": self.condition_code,
        }


class DataVariable(db.Model):
    __tablename__ = "data_variables"

    id = db.Column(db.Integer, primary_key=True)
    variable_name = db.Column(db.String(50), unique=True, nullable=False)
    unit = db.Column(db.String(20), nullable=False)
    description = db.Column(db.Text)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "variable_name": self.variable_name,
            "unit": self.unit,
            "description": self.description,
        }
