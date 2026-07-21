"""Notification routes (no error handling — target for P3)."""

from flask import Blueprint, request, jsonify
from src.db.queries import execute_query, execute_write

notifications_bp = Blueprint("notifications", __name__)


@notifications_bp.route("/notifications", methods=["GET"])
def list_notifications():
    user_id = request.args.get("user_id", type=int)
    rows = execute_query("SELECT * FROM notifications WHERE user_id = ? ORDER BY id DESC", (user_id,))
    return jsonify(rows)


@notifications_bp.route("/notifications", methods=["POST"])
def create_notification():
    data = request.get_json()
    notif_id = execute_write(
        "INSERT INTO notifications (user_id, message, read) VALUES (?, ?, 0)",
        (data["user_id"], data["message"]),
    )
    return jsonify({"id": notif_id}), 201


@notifications_bp.route("/notifications/<int:notif_id>/read", methods=["PUT"])
def mark_read(notif_id):
    execute_write("UPDATE notifications SET read = 1 WHERE id = ?", (notif_id,))
    return jsonify({"marked_read": notif_id})
