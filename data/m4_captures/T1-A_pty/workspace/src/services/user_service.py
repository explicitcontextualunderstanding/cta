"""User service layer (raw SQL — target for P2 migration)."""

from src.db.queries import execute_query, execute_write


def get_user_orders(user_id: int) -> list[dict]:
    return execute_query("SELECT * FROM orders WHERE user_id = ? ORDER BY id DESC", (user_id,))


def get_user_stats(user_id: int) -> dict:
    orders = execute_query("SELECT COUNT(*) as count, SUM(total) as spent FROM orders WHERE user_id = ?", (user_id,))
    return orders[0] if orders else {"count": 0, "spent": 0}


def deactivate_user(user_id: int) -> None:
    execute_write("UPDATE users SET active = 0 WHERE id = ?", (user_id,))
    execute_write("DELETE FROM sessions WHERE user_id = ?", (user_id,))
