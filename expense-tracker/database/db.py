"""Database layer for the expense tracker (Step 1 — Database Setup).

Everything that touches SQLite lives here so the rest of the app never has
to think about connections or SQL plumbing.

Public API
----------
    get_db()        -> an open sqlite3 connection for the current request
    close_db()      -> close that connection (wired up as a Flask teardown)
    init_db()       -> create the tables if they don't exist (idempotent)
    seed_db()       -> insert a demo user + sample expenses (dev convenience)
    init_app(app)   -> register teardown + a `flask init-db` CLI command
"""

import sqlite3

import click
from flask import current_app, g


# ------------------------------------------------------------------ #
# Connection handling                                                 #
# ------------------------------------------------------------------ #

def get_db():
    """Return the SQLite connection for the current request.

    The connection is cached on ``flask.g`` so that many calls within the
    same request share one connection. It is created lazily the first time
    it's needed, and closed by ``close_db`` when the request ends.
    """
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        # Rows behave like dicts: row["email"] instead of row[2].
        g.db.row_factory = sqlite3.Row
        # SQLite does NOT enforce foreign keys unless you ask it to, per
        # connection. We rely on ON DELETE CASCADE, so turn it on.
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(exc=None):
    """Close the request's connection if one was opened."""
    db = g.pop("db", None)
    if db is not None:
        db.close()


# ------------------------------------------------------------------ #
# Schema + setup                                                      #
# ------------------------------------------------------------------ #

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    email         TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS expenses (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    amount      REAL    NOT NULL CHECK (amount > 0),
    category    TEXT    NOT NULL,
    description TEXT    NOT NULL DEFAULT '',
    spent_on    TEXT    NOT NULL,          -- expense date, stored as YYYY-MM-DD
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
);

-- Speeds up the common "all of a user's expenses, newest first" query.
CREATE INDEX IF NOT EXISTS idx_expenses_user ON expenses (user_id, spent_on);
"""


def init_db():
    """Create all tables. Safe to call repeatedly (CREATE ... IF NOT EXISTS)."""
    db = get_db()
    db.executescript(SCHEMA)
    db.commit()


def seed_db():
    """Insert one demo account and a handful of expenses, for development.

    Idempotent: if the demo user already exists we do nothing. Returns the
    demo user's id either way.

    Demo login -> email: demo@example.com   password: password123
    """
    from werkzeug.security import generate_password_hash

    db = get_db()
    existing = db.execute(
        "SELECT id FROM users WHERE email = ?", ("demo@example.com",)
    ).fetchone()
    if existing:
        return existing["id"]

    cur = db.execute(
        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
        ("Demo User", "demo@example.com", generate_password_hash("password123")),
    )
    user_id = cur.lastrowid

    samples = [
        (user_id, 450.00, "Food", "Team lunch", "2026-10-02"),
        (user_id, 1200.00, "Bills", "Electricity bill", "2026-10-05"),
        (user_id, 300.00, "Travel", "Auto + metro", "2026-10-07"),
        (user_id, 899.00, "Shopping", "New headphones", "2026-10-09"),
        (user_id, 150.00, "Food", "Evening coffee", "2026-10-11"),
        (user_id, 2000.00, "Bills", "Home internet", "2026-10-12"),
        (user_id, 520.00, "Entertainment", "Movie night", "2026-10-13"),
    ]
    db.executemany(
        "INSERT INTO expenses (user_id, amount, category, description, spent_on) "
        "VALUES (?, ?, ?, ?, ?)",
        samples,
    )
    db.commit()
    return user_id


# ------------------------------------------------------------------ #
# App wiring                                                          #
# ------------------------------------------------------------------ #

def init_app(app):
    """Hook the database into a Flask app.

    - closes the connection automatically at the end of every request
    - adds a `flask init-db` command so you can (re)create tables by hand
    """
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)


@click.command("init-db")
def init_db_command():
    """CLI: `flask init-db` — create the database tables."""
    init_db()
    click.echo("Initialized the database.")
