"""
Unit tests for the /auth endpoints (register, login, logout).

These tests use an isolated, in-memory SQLite database that exists only for
the duration of the test run — no PostgreSQL setup is required, and the real
`meteocity` database is never touched. Only the `User` table is created,
since these tests don't exercise anything involving the PostGIS-backed
WeatherStation table.

Run with:
    pytest tests/test_auth.py -v
or, to run the whole suite:
    pytest tests/ -v
"""

import os
import sys

import pytest

# Allow running `pytest tests/` from the project root to resolve `backend.*` imports
_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from backend.app import create_app
from backend.models import db, User, revoked_tokens


@pytest.fixture()
def app():
    """Flask app configured for testing, backed by an in-memory SQLite DB."""
    flask_app = create_app("default")
    flask_app.config.update(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        }
    )

    with flask_app.app_context():
        User.__table__.create(db.engine, checkfirst=True)
        yield flask_app
        db.session.remove()
        User.__table__.drop(db.engine, checkfirst=True)
        revoked_tokens.clear()


@pytest.fixture()
def client(app):
    return app.test_client()


def register(client, username="alice", password="secret123", role="user"):
    return client.post(
        "/auth/register",
        json={"username": username, "password": password, "role": role},
    )


def login(client, username="alice", password="secret123"):
    return client.post(
        "/auth/login",
        json={"username": username, "password": password},
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_register_success(client):
    response = register(client)
    assert response.status_code == 201
    body = response.get_json()
    assert body["message"] == "User registered successfully"
    assert body["user"]["username"] == "alice"
    assert body["user"]["role"] == "user"


def test_register_missing_username(client):
    response = client.post(
        "/auth/register", json={"password": "secret123"}
    )
    assert response.status_code == 400


def test_register_missing_password(client):
    response = client.post(
        "/auth/register", json={"username": "alice"}
    )
    assert response.status_code == 400


def test_register_password_too_short(client):
    response = register(client, password="abc")
    assert response.status_code == 400
    assert "6 characters" in response.get_json()["error"]


def test_register_invalid_role(client):
    response = register(client, role="admin")
    assert response.status_code == 400


def test_register_duplicate_username(client):
    first = register(client)
    assert first.status_code == 201

    second = register(client)
    assert second.status_code == 409


def test_register_ngo_role_uppercase_is_normalized(client):
    """
    Documents that the backend lowercases the role before validating it, so
    a frontend sending role="NGO" is correctly accepted and stored as "ngo".
    If this test starts failing, the case-normalization logic in
    backend/routes/auth.py has changed and the known NGO registration bug
    may be re-introduced.
    """
    response = register(client, username="ngo_user", role="NGO")
    assert response.status_code == 201
    assert response.get_json()["user"]["role"] == "ngo"


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

def test_login_success(client):
    register(client)
    response = login(client)
    assert response.status_code == 200
    body = response.get_json()
    assert "access_token" in body
    assert body["username"] == "alice"
    assert body["role"] == "user"


def test_login_wrong_password(client):
    register(client)
    response = login(client, password="wrongpassword")
    assert response.status_code == 401


def test_login_nonexistent_user(client):
    response = login(client, username="ghost")
    assert response.status_code == 401


def test_login_missing_fields(client):
    response = client.post("/auth/login", json={"username": "alice"})
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------

def test_logout_revokes_token(client):
    register(client)
    token = login(client).get_json()["access_token"]

    first_logout = client.get(
        "/auth/logout", headers={"Authorization": f"Bearer {token}"}
    )
    assert first_logout.status_code == 200

    # The same token should now be rejected as revoked
    second_logout = client.get(
        "/auth/logout", headers={"Authorization": f"Bearer {token}"}
    )
    assert second_logout.status_code == 401


def test_logout_without_token(client):
    response = client.get("/auth/logout")
    assert response.status_code == 401
