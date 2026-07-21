"""User model with raw SQL queries (pre-migration state for P2)."""

import sqlite3


class User:
    def __init__(self, db_path="app.db"):
        self.db_path = db_path

    def get_by_id(self, user_id: int) -> dict | None:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute(
            "SELECT id, username, email, password_hash FROM users WHERE id = ?",
            (user_id,),
        )
        row = cursor.fetchone()
        conn.close()
        if row:
            return {"id": row[0], "username": row[1], "email": row[2], "password_hash": row[3]}
        return None

    def get_by_email(self, email: str) -> dict | None:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute(
            "SELECT id, username, email, password_hash FROM users WHERE email = ?",
            (email,),
        )
        row = cursor.fetchone()
        conn.close()
        if row:
            return {"id": row[0], "username": row[1], "email": row[2], "password_hash": row[3]}
        return None

    def create(self, username: str, email: str, password_hash: str) -> int:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute(
            "INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)",
            (username, email, password_hash),
        )
        conn.commit()
        user_id = cursor.lastrowid
        conn.close()
        return user_id

    def list_all(self, limit: int = 100) -> list[dict]:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute(
            "SELECT id, username, email FROM users ORDER BY id LIMIT ?", (limit,)
        )
        rows = cursor.fetchall()
        conn.close()
        return [{"id": r[0], "username": r[1], "email": r[2]} for r in rows]
