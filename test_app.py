"""Tests for the JWT auth API."""
import pytest
import jwt
from app import app

@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client

def test_login_success(client):
    resp = client.post('/api/login', json={'username': 'admin', 'password': 'testpass123'})
    assert resp.status_code == 200
    data = resp.get_json()
    assert 'token' in data

def test_protected_without_token(client):
    resp = client.get('/api/protected')
    assert resp.status_code == 401

def test_protected_with_valid_token(client):
    resp = client.post('/api/login', json={'username': 'admin', 'password': 'testpass123'})
    token = resp.get_json()['token']
    resp = client.get('/api/protected', headers={'Authorization': token})
    assert resp.status_code == 200
