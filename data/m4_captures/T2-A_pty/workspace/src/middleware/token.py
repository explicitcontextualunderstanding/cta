"""Authentication middleware (stub — target for P1)."""


def verify_token(token: str) -> dict | None:
    """Verify a JWT token and return the user payload."""
    # TODO: implement token verification
    return None


def require_auth(f):
    """Decorator to require authentication on a route."""
    from functools import wraps
    from flask import request, jsonify

    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "missing token"}), 401
        token = auth_header[7:]
        payload = verify_token(token)
        if payload is None:
            return jsonify({"error": "invalid token"}), 401
        request.user = payload
        return f(*args, **kwargs)

    return decorated
