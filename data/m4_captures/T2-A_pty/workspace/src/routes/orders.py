"""Order routes (no error handling — target for P3)."""

from flask import Blueprint, request, jsonify
from src.db.queries import execute_query, execute_write

orders_bp = Blueprint("orders", __name__)


@orders_bp.route("/orders", methods=["GET"])
def list_orders():
    rows = execute_query("SELECT id, user_id, total, status FROM orders ORDER BY id DESC")
    return jsonify(rows)


@orders_bp.route("/orders/<int:order_id>", methods=["GET"])
def get_order(order_id):
    rows = execute_query("SELECT * FROM orders WHERE id = ?", (order_id,))
    if not rows:
        return jsonify({"error": "not found"}), 404
    return jsonify(rows[0])


@orders_bp.route("/orders", methods=["POST"])
def create_order():
    data = request.get_json()
    order_id = execute_write(
        "INSERT INTO orders (user_id, total, status) VALUES (?, ?, ?)",
        (data["user_id"], data["total"], "pending"),
    )
    return jsonify({"id": order_id}), 201


@orders_bp.route("/orders/<int:order_id>/cancel", methods=["POST"])
def cancel_order(order_id):
    execute_write("UPDATE orders SET status = 'cancelled' WHERE id = ?", (order_id,))
    return jsonify({"cancelled": order_id})
