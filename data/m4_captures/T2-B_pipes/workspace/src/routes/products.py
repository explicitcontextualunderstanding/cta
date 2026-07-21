"""Product routes (no error handling — target for P3)."""

from flask import Blueprint, request, jsonify
from src.db.queries import execute_query, execute_write

products_bp = Blueprint("products", __name__)


@products_bp.route("/products", methods=["GET"])
def list_products():
    rows = execute_query("SELECT id, name, price, stock FROM products ORDER BY name")
    return jsonify(rows)


@products_bp.route("/products/<int:product_id>", methods=["GET"])
def get_product(product_id):
    rows = execute_query("SELECT * FROM products WHERE id = ?", (product_id,))
    if not rows:
        return jsonify({"error": "not found"}), 404
    return jsonify(rows[0])


@products_bp.route("/products", methods=["POST"])
def create_product():
    data = request.get_json()
    product_id = execute_write(
        "INSERT INTO products (name, price, stock) VALUES (?, ?, ?)",
        (data["name"], data["price"], data["stock"]),
    )
    return jsonify({"id": product_id}), 201


@products_bp.route("/products/<int:product_id>", methods=["PUT"])
def update_product(product_id):
    data = request.get_json()
    execute_write(
        "UPDATE products SET name = ?, price = ?, stock = ? WHERE id = ?",
        (data["name"], data["price"], data["stock"], product_id),
    )
    return jsonify({"updated": product_id})


@products_bp.route("/products/<int:product_id>", methods=["DELETE"])
def delete_product(product_id):
    execute_write("DELETE FROM products WHERE id = ?", (product_id,))
    return "", 204
