"""JWT authentication middleware."""

import os
from functools import wraps

import jwt
from flask import request, jsonify

SECRET_KEY = os.environ.get("JWT_SECRET", "dev-secret-change-in-production!")
ALGORITHM = "HS256"
TOKEN_EXPIRY_SECONDS = 3600


def generate_token(user_id: int, email: str) -> str:
    import time

    payload = {
        "sub": str(user_id),
        "email": email,
        "iat": int(time.time()),
        "exp": int(time.time()) + TOKEN_EXPIRY_SECONDS,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def verify_token(token: str) -> dict | None:
    """Verify a JWT token and return the user payload."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        payload["sub"] = int(payload["sub"])
        return payload
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError, KeyError, ValueError):
        return None


def require_auth(f):
    """Decorator to require authentication on a route."""

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
