"""Authentication routes: register and login."""

from flask import Blueprint, request, jsonify
from werkzeug.security import generate_password_hash, check_password_hash

from src.models.user import User
from src.middleware.token import create_token, require_auth

auth_bp = Blueprint("auth", __name__)
user_model = User()


@auth_bp.route("/auth/register", methods=["POST"])
def register():
    data = request.get_json()
    if not data or not data.get("username") or not data.get("email") or not data.get("password"):
        return jsonify({"error": "username, email, and password are required"}), 400

    existing = user_model.get_by_email(data["email"])
    if existing:
        return jsonify({"error": "email already registered"}), 409

    password_hash = generate_password_hash(data["password"])
    user_id = user_model.create(
        username=data["username"],
        email=data["email"],
        password_hash=password_hash,
    )
    token = create_token(user_id, data["username"])
    return jsonify({"id": user_id, "token": token}), 201


@auth_bp.route("/auth/login", methods=["POST"])
def login():
    data = request.get_json()
    if not data or not data.get("email") or not data.get("password"):
        return jsonify({"error": "email and password are required"}), 400

    user = user_model.get_by_email(data["email"])
    if user is None or not check_password_hash(user["password_hash"], data["password"]):
        return jsonify({"error": "invalid credentials"}), 401

    token = create_token(user["id"], user["username"])
    return jsonify({"token": token, "user_id": user["id"]})


@auth_bp.route("/auth/me", methods=["GET"])
@require_auth
def me():
    return jsonify({"user_id": request.user["user_id"], "username": request.user["username"]})
