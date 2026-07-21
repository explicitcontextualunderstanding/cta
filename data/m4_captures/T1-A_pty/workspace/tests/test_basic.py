"""Basic tests for the fixture project."""

import pytest
from src.utils.helpers import format_currency, slugify, paginate


def test_format_currency():
    assert format_currency(1234.5) == "$1,234.50"
    assert format_currency(0) == "$0.00"


def test_slugify():
    assert slugify("Hello World") == "hello-world"
    assert slugify("foo_bar") == "foo-bar"


def test_paginate():
    items = list(range(50))
    result = paginate(items, page=2, per_page=10)
    assert result["items"] == list(range(10, 20))
    assert result["total"] == 50
