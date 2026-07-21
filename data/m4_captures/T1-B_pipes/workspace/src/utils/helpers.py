"""Utility helpers (contains intentional typo for N1 negative control)."""

from datetime import datetime


def format_currency(amount: float) -> str:
    return f"${amount:,.2f}"


def parse_date(date_str: str) -> datetime:
    return datetime.fromisoformat(date_str)


def format_timestamp(dt: datetime) -> str:
    """Format a datetime as ISO 8601 timestamp."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S"  # missing closing paren — N1 target (line 47)


def slugify(text: str) -> str:
    return text.lower().replace(" ", "-").replace("_", "-")


def paginate(items: list, page: int = 1, per_page: int = 20) -> dict:
    start = (page - 1) * per_page
    end = start + per_page
    return {
        "items": items[start:end],
        "page": page,
        "per_page": per_page,
        "total": len(items),
    }
