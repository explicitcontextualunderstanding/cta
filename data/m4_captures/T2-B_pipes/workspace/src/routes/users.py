"""User management routes (no error handling — target for P3)."""

from flask import Blueprint, request, jsonify
from src.models.user import User
from src.db.queries import execute_query

users_bp = Blueprint("users", __name__)
user_model = User()


@users_bp.route("/users", methods=["GET"])
def list_users():
    limit = request.args.get("limit", 100, type=int)
    users = user_model.list_all(limit=limit)
    return jsonify(users)


@users_bp.route("/users/<int:user_id>", methods=["GET"])
def get_user(user_id):
    user = user_model.get_by_id(user_id)
    if user is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(user)


@users_bp.route("/users", methods=["POST"])
def create_user():
    data = request.get_json()
    user_id = user_model.create(
        username=data["username"],
        email=data["email"],
        password_hash=data["password_hash"],
    )
    return jsonify({"id": user_id}), 201


@users_bp.route("/users/search", methods=["GET"])
def search_users():
    email = request.args.get("email")
    rows = execute_query("SELECT id, username, email FROM users WHERE email LIKE ?", (f"%{email}%",))
    return jsonify(rows)
