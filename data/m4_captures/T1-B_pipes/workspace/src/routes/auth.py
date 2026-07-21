"""Authentication routes: register and login."""

from flask import Blueprint, request, jsonify
from werkzeug.security import generate_password_hash, check_password_hash

from src.models.user import User
from src.middleware.token import generate_token, require_auth

auth_bp = Blueprint("auth", __name__)
user_model = User()


@auth_bp.route("/auth/register", methods=["POST"])
def register():
    data = request.get_json()
    if not data or not data.get("email") or not data.get("password") or not data.get("username"):
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
    token = generate_token(user_id, data["email"])
    return jsonify({"id": user_id, "token": token}), 201


@auth_bp.route("/auth/login", methods=["POST"])
def login():
    data = request.get_json()
    if not data or not data.get("email") or not data.get("password"):
        return jsonify({"error": "email and password are required"}), 400

    user = user_model.get_by_email(data["email"])
    if user is None or not check_password_hash(user["password_hash"], data["password"]):
        return jsonify({"error": "invalid credentials"}), 401

    token = generate_token(user["id"], user["email"])
    return jsonify({"id": user["id"], "token": token}), 200


@auth_bp.route("/auth/me", methods=["GET"])
@require_auth
def me():
    return jsonify({"id": request.user["sub"], "email": request.user["email"]}), 200
