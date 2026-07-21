"""Tests for authentication endpoints and JWT middleware."""

import pytest
from src.app import create_app
from src.middleware.token import create_token, verify_token
from src.db.queries import init_db
import os
import tempfile


@pytest.fixture
def app(tmp_path):
    db_path = str(tmp_path / "test.db")
    os.environ.setdefault("DB_PATH", db_path)

    import src.db.queries as queries
    original_db_path = queries.DB_PATH
    queries.DB_PATH = db_path

    from src.models.user import User
    import src.routes.auth as auth_module
    import src.routes.users as users_module

    auth_module.user_model = User(db_path=db_path)
    users_module.user_model = User(db_path=db_path)

    init_db()
    application = create_app()
    application.config["TESTING"] = True

    yield application

    queries.DB_PATH = original_db_path


@pytest.fixture
def client(app):
    return app.test_client()


class TestTokenMiddleware:
    def test_create_and_verify_token(self):
        token = create_token(user_id=1, username="alice")
        payload = verify_token(token)
        assert payload is not None
        assert payload["user_id"] == 1
        assert payload["username"] == "alice"

    def test_verify_invalid_token(self):
        assert verify_token("garbage.token.here") is None

    def test_verify_empty_token(self):
        assert verify_token("") is None


class TestRegister:
    def test_register_success(self, client):
        resp = client.post("/auth/register", json={
            "username": "alice",
            "email": "alice@example.com",
            "password": "securepass123",
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert "id" in data
        assert "token" in data

    def test_register_missing_fields(self, client):
        resp = client.post("/auth/register", json={"username": "bob"})
        assert resp.status_code == 400

    def test_register_duplicate_email(self, client):
        payload = {"username": "alice", "email": "dup@example.com", "password": "pass123"}
        client.post("/auth/register", json=payload)
        resp = client.post("/auth/register", json={
            "username": "bob",
            "email": "dup@example.com",
            "password": "pass456",
        })
        assert resp.status_code == 409


class TestLogin:
    def test_login_success(self, client):
        client.post("/auth/register", json={
            "username": "carol",
            "email": "carol@example.com",
            "password": "mypassword",
        })
        resp = client.post("/auth/login", json={
            "email": "carol@example.com",
            "password": "mypassword",
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert "token" in data
        assert "user_id" in data

    def test_login_wrong_password(self, client):
        client.post("/auth/register", json={
            "username": "dave",
            "email": "dave@example.com",
            "password": "correct",
        })
        resp = client.post("/auth/login", json={
            "email": "dave@example.com",
            "password": "wrong",
        })
        assert resp.status_code == 401

    def test_login_nonexistent_user(self, client):
        resp = client.post("/auth/login", json={
            "email": "nobody@example.com",
            "password": "pass",
        })
        assert resp.status_code == 401

    def test_login_missing_fields(self, client):
        resp = client.post("/auth/login", json={"email": "x@y.com"})
        assert resp.status_code == 400


class TestProtectedRoute:
    def test_me_with_valid_token(self, client):
        reg = client.post("/auth/register", json={
            "username": "eve",
            "email": "eve@example.com",
            "password": "pass123",
        })
        token = reg.get_json()["token"]
        resp = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["username"] == "eve"

    def test_me_without_token(self, client):
        resp = client.get("/auth/me")
        assert resp.status_code == 401

    def test_me_with_invalid_token(self, client):
        resp = client.get("/auth/me", headers={"Authorization": "Bearer invalid.token"})
        assert resp.status_code == 401
