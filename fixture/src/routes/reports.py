"""Report routes (no error handling — target for P3)."""

from flask import Blueprint, request, jsonify
from src.db.queries import execute_query

reports_bp = Blueprint("reports", __name__)


@reports_bp.route("/reports/sales", methods=["GET"])
def sales_report():
    period = request.args.get("period", "monthly")
    rows = execute_query(
        "SELECT strftime('%Y-%m', timestamp) as period, SUM(total) as revenue FROM orders GROUP BY period ORDER BY period DESC LIMIT 12"
    )
    return jsonify({"period": period, "data": rows})


@reports_bp.route("/reports/users", methods=["GET"])
def user_report():
    rows = execute_query(
        "SELECT COUNT(*) as total, strftime('%Y-%m', timestamp) as cohort FROM users GROUP BY cohort"
    )
    return jsonify(rows)
