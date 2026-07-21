"""Flask application entry point."""

from flask import Flask
from src.routes.users import users_bp
from src.routes.products import products_bp
from src.routes.orders import orders_bp
from src.routes.payments import payments_bp
from src.routes.inventory import inventory_bp
from src.routes.reports import reports_bp
from src.routes.notifications import notifications_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.register_blueprint(users_bp)
    app.register_blueprint(products_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(payments_bp)
    app.register_blueprint(inventory_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(notifications_bp)
    return app


if __name__ == "__main__":
    app = create_app()
    app.run(debug=True, port=5000)
