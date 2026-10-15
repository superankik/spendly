"""Database layer for Spendwise.

Everything that talks to SQLite lives here so the rest of the app never
has to think about connections, cursors, or SQL plumbing.

Public functions:
    get_db()   -> a per-request SQLite connection (Row factory + FK on)
    close_db() -> closes that connection at the end of the request
    init_db()  -> creates the tables (safe to call repeatedly)
    seed_db()  -> inserts demo data for development (only if empty)
    init_app() -> wires the above into a Flask app
"""

import sqlite3
from datetime import date, timedelta

from flask import current_app, g
from werkzeug.security import generate_password_hash


# The schema. CREATE TABLE IF NOT EXISTS means init_db() can run on every
# startup without complaining that the tables already exist.
SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT    NOT NULL,
    email         TEXT    NOT NULL UNIQUE,
    password_hash TEXT    NOT NULL,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS expenses (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    amount      REAL    NOT NULL,
    category    TEXT    NOT NULL,
    description TEXT    NOT NULL DEFAULT '',
    spent_on    TEXT    NOT NULL,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
);
"""


def get_db():
    """Return the SQLite connection for the current request.

    The connection is cached on Flask's ``g`` object so that every call
    within a single request reuses the same connection (and transaction).
    """
    if "db" not in g:
        g.db = sqlite3.connect(
            current_app.config["DATABASE"],
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
        # Rows behave like dicts: row["email"] instead of row[2].
        g.db.row_factory = sqlite3.Row
        # SQLite does NOT enforce foreign keys unless you ask it to, per connection.
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(exception=None):
    """Close the request's connection, if one was opened."""
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    """Create all tables. Safe to call on every startup."""
    db = get_db()
    db.executescript(SCHEMA)
    db.commit()


def seed_db():
    """Insert a demo user and some sample expenses — but only if the
    database is empty, so repeated runs don't pile up duplicates.

    Returns the demo login credentials (or None if data already existed).
    """
    db = get_db()
    existing = db.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
    if existing:
        return None

    demo_email = "demo@spendwise.app"
    demo_password = "spendwise123"
    cursor = db.execute(
        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
        ("Demo User", demo_email, generate_password_hash(demo_password)),
    )
    user_id = cursor.lastrowid

    today = date.today()
    sample = [
        (420.0,  "Food",          "Lunch with team",        today - timedelta(days=1)),
        (89.0,   "Travel",        "Auto to office",         today - timedelta(days=1)),
        (1499.0, "Bills",         "Electricity bill",       today - timedelta(days=3)),
        (2300.0, "Shopping",      "Running shoes",          today - timedelta(days=5)),
        (650.0,  "Food",          "Groceries",              today - timedelta(days=6)),
        (199.0,  "Entertainment", "Movie ticket",           today - timedelta(days=8)),
        (750.0,  "Health",        "Pharmacy",               today - timedelta(days=11)),
        (310.0,  "Travel",        "Cab to airport",         today - timedelta(days=14)),
    ]
    db.executemany(
        "INSERT INTO expenses (user_id, amount, category, description, spent_on) "
        "VALUES (?, ?, ?, ?, ?)",
        [(user_id, amt, cat, desc, d.isoformat()) for (amt, cat, desc, d) in sample],
    )
    db.commit()
    return {"email": demo_email, "password": demo_password}


def init_app(app):
    """Register database hooks with the Flask application."""
    # Close the connection automatically when each request/app context ends.
    app.teardown_appcontext(close_db)
