"""Payment routes (no error handling — target for P3)."""

from flask import Blueprint, request, jsonify
from src.db.queries import execute_query, execute_write

payments_bp = Blueprint("payments", __name__)


@payments_bp.route("/payments", methods=["GET"])
def list_payments():
    rows = execute_query("SELECT id, order_id, amount, method, status FROM payments")
    return jsonify(rows)


@payments_bp.route("/payments/<int:payment_id>", methods=["GET"])
def get_payment(payment_id):
    rows = execute_query("SELECT * FROM payments WHERE id = ?", (payment_id,))
    if not rows:
        return jsonify({"error": "not found"}), 404
    return jsonify(rows[0])


@payments_bp.route("/payments", methods=["POST"])
def process_payment():
    data = request.get_json()
    payment_id = execute_write(
        "INSERT INTO payments (order_id, amount, method, status) VALUES (?, ?, ?, ?)",
        (data["order_id"], data["amount"], data["method"], "completed"),
    )
    return jsonify({"id": payment_id}), 201
