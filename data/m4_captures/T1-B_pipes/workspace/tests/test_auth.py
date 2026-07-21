"""Tests for authentication endpoints and JWT middleware."""

import sqlite3
import tempfile
import os

import pytest

from src.app import create_app
from src.models.user import User
from src.middleware.token import generate_token, verify_token


@pytest.fixture
def db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, email TEXT, password_hash TEXT)"
    )
    conn.commit()
    conn.close()
    yield path
    os.unlink(path)


@pytest.fixture
def app(db_path, monkeypatch):
    monkeypatch.setattr("src.routes.auth.user_model", User(db_path=db_path))
    application = create_app()
    application.config["TESTING"] = True
    return application


@pytest.fixture
def client(app):
    return app.test_client()


class TestRegister:
    def test_register_success(self, client):
        resp = client.post("/auth/register", json={
            "username": "alice",
            "email": "alice@example.com",
            "password": "securepass123",
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["id"] == 1
        assert "token" in data

    def test_register_missing_fields(self, client):
        resp = client.post("/auth/register", json={"email": "a@b.com"})
        assert resp.status_code == 400

    def test_register_duplicate_email(self, client):
        payload = {"username": "bob", "email": "bob@example.com", "password": "pass123"}
        client.post("/auth/register", json=payload)
        resp = client.post("/auth/register", json=payload)
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
        assert "token" in resp.get_json()

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


class TestTokenMiddleware:
    def test_generate_and_verify_token(self):
        token = generate_token(42, "test@example.com")
        payload = verify_token(token)
        assert payload is not None
        assert payload["sub"] == 42
        assert payload["email"] == "test@example.com"

    def test_verify_invalid_token(self):
        assert verify_token("garbage.token.here") is None

    def test_me_endpoint_with_valid_token(self, client):
        reg = client.post("/auth/register", json={
            "username": "eve",
            "email": "eve@example.com",
            "password": "pass123",
        })
        token = reg.get_json()["token"]
        resp = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["email"] == "eve@example.com"

    def test_me_endpoint_without_token(self, client):
        resp = client.get("/auth/me")
        assert resp.status_code == 401

    def test_me_endpoint_with_invalid_token(self, client):
        resp = client.get("/auth/me", headers={"Authorization": "Bearer invalid.token"})
        assert resp.status_code == 401
