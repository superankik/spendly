"""Shared pytest fixtures.

Each test gets a brand-new Flask app pointed at its own throwaway SQLite
file, so tests are fully isolated and never touch the real database.
"""

import os
import tempfile

import pytest

from app import create_app


@pytest.fixture
def app():
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    application = create_app({
        "TESTING": True,
        "DATABASE": db_path,
        "SECRET_KEY": "test-secret",
    })
    yield application
    os.close(db_fd)
    os.unlink(db_path)


@pytest.fixture
def client(app):
    return app.test_client()


class AuthActions:
    """Convenience wrapper so tests can register/login/logout in one line."""

    def __init__(self, client):
        self._client = client

    def register(self, name="Test User", email="test@example.com",
                 password="password123"):
        return self._client.post("/register", data={
            "name": name, "email": email, "password": password,
        })

    def login(self, email="test@example.com", password="password123"):
        return self._client.post("/login", data={
            "email": email, "password": password,
        })

    def logout(self):
        return self._client.get("/logout")


@pytest.fixture
def auth(client):
    return AuthActions(client)
