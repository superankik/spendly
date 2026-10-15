"""Pytest fixtures.

Each test gets a brand-new, empty SQLite database in a temp file, so tests
are fully isolated from each other and from the real expense_tracker.db.
"""

import os
import tempfile

import pytest

import app as app_module


@pytest.fixture
def app():
    """The Flask app, pointed at a throwaway database with empty tables."""
    db_fd, db_path = tempfile.mkstemp(suffix=".db")

    flask_app = app_module.app
    flask_app.config.update(
        TESTING=True,
        DATABASE=db_path,
        SECRET_KEY="test-secret",
    )

    with flask_app.app_context():
        app_module.db.init_db()

    yield flask_app

    os.close(db_fd)
    os.unlink(db_path)


@pytest.fixture
def client(app):
    return app.test_client()
