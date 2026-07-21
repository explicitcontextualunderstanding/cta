"""Inventory routes (no error handling — target for P3)."""

from flask import Blueprint, request, jsonify
from src.db.queries import execute_query, execute_write

inventory_bp = Blueprint("inventory", __name__)


@inventory_bp.route("/inventory", methods=["GET"])
def list_inventory():
    rows = execute_query("SELECT p.id, p.name, p.stock, w.location FROM products p JOIN warehouse w ON p.id = w.product_id")
    return jsonify(rows)


@inventory_bp.route("/inventory/<int:product_id>", methods=["GET"])
def get_inventory(product_id):
    rows = execute_query("SELECT * FROM warehouse WHERE product_id = ?", (product_id,))
    if not rows:
        return jsonify({"error": "not found"}), 404
    return jsonify(rows[0])


@inventory_bp.route("/inventory/adjust", methods=["POST"])
def adjust_stock():
    data = request.get_json()
    execute_write(
        "UPDATE products SET stock = stock + ? WHERE id = ?",
        (data["delta"], data["product_id"]),
    )
    return jsonify({"adjusted": data["product_id"], "delta": data["delta"]})
