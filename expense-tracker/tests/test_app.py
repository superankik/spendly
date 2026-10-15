"""End-to-end tests driving the app through its HTTP routes.

Each test starts from an empty database (see conftest.py), so IDs are
deterministic: the first registered user is id 1, the first expense is id 1,
and so on.
"""

import app as app_module


# ------------------------------------------------------------------ #
# Small helpers that drive the app like a browser would               #
# ------------------------------------------------------------------ #

def register(client, name="Test User", email="test@example.com",
             password="password123"):
    return client.post(
        "/register",
        data={"name": name, "email": email, "password": password},
        follow_redirects=True,
    )


def login(client, email="test@example.com", password="password123"):
    return client.post(
        "/login",
        data={"email": email, "password": password},
        follow_redirects=True,
    )


def add_expense(client, amount="100", category="Food", description="Test item",
                spent_on="2026-10-10"):
    return client.post(
        "/expenses/add",
        data={"amount": amount, "category": category,
              "description": description, "spent_on": spent_on},
        follow_redirects=True,
    )


def count_expenses(app):
    with app.app_context():
        return app_module.db.get_db().execute(
            "SELECT COUNT(*) AS n FROM expenses"
        ).fetchone()["n"]


# ------------------------------------------------------------------ #
# Public pages                                                        #
# ------------------------------------------------------------------ #

def test_landing_loads(client):
    r = client.get("/")
    assert r.status_code == 200
    assert b"Spendly" in r.data


def test_terms_and_privacy_load(client):
    assert client.get("/terms").status_code == 200
    assert client.get("/privacy").status_code == 200


# ------------------------------------------------------------------ #
# Registration                                                        #
# ------------------------------------------------------------------ #

def test_register_logs_user_in(client):
    r = register(client)
    assert r.status_code == 200
    assert b"Your expenses" in r.data          # landed on the dashboard


def test_register_rejects_duplicate_email(client):
    register(client)
    client.get("/logout")
    r = register(client, name="Someone Else")  # same email
    assert b"already registered" in r.data


def test_register_rejects_short_password(client):
    r = register(client, password="short")
    assert b"at least 8 characters" in r.data


def test_register_rejects_blank_name(client):
    r = register(client, name="   ")
    assert b"enter your name" in r.data


# ------------------------------------------------------------------ #
# Login / logout                                                      #
# ------------------------------------------------------------------ #

def test_login_with_correct_credentials(client):
    register(client)
    client.get("/logout")
    r = login(client)
    assert b"Your expenses" in r.data


def test_login_with_wrong_password(client):
    register(client)
    client.get("/logout")
    r = login(client, password="wrongpassword")
    assert b"Incorrect email or password" in r.data


def test_login_unknown_email(client):
    r = login(client, email="nobody@example.com")
    assert b"Incorrect email or password" in r.data


def test_logout_ends_session(client):
    register(client)
    client.get("/logout")
    r = client.get("/dashboard", follow_redirects=True)
    assert b"Welcome back" in r.data            # bounced to the login page


# ------------------------------------------------------------------ #
# Access control                                                      #
# ------------------------------------------------------------------ #

def test_dashboard_requires_login(client):
    r = client.get("/dashboard", follow_redirects=True)
    assert b"Welcome back" in r.data


def test_add_expense_requires_login(client):
    r = client.get("/expenses/add", follow_redirects=True)
    assert b"Welcome back" in r.data


# ------------------------------------------------------------------ #
# Adding expenses                                                     #
# ------------------------------------------------------------------ #

def test_add_expense_shows_on_dashboard(client):
    register(client)
    r = add_expense(client, amount="250.50", category="Food",
                    description="Team lunch")
    assert b"Team lunch" in r.data
    assert "₹250.50".encode() in r.data


def test_add_expense_rejects_non_numeric_amount(client, app):
    register(client)
    r = add_expense(client, amount="abc")
    assert b"Amount must be a number" in r.data
    assert count_expenses(app) == 0


def test_add_expense_rejects_negative_amount(client, app):
    register(client)
    r = add_expense(client, amount="-5")
    assert b"greater than zero" in r.data
    assert count_expenses(app) == 0


def test_add_expense_rejects_bad_category(client, app):
    register(client)
    r = add_expense(client, category="NotACategory")
    assert b"valid category" in r.data
    assert count_expenses(app) == 0


# ------------------------------------------------------------------ #
# Editing + deleting                                                  #
# ------------------------------------------------------------------ #

def test_edit_expense_updates_values(client, app):
    register(client)
    add_expense(client, amount="100", description="Original")
    client.post(
        "/expenses/1/edit",
        data={"amount": "175", "category": "Travel",
              "description": "Updated", "spent_on": "2026-10-11"},
        follow_redirects=True,
    )
    with app.app_context():
        row = app_module.db.get_db().execute(
            "SELECT * FROM expenses WHERE id = 1"
        ).fetchone()
    assert row["amount"] == 175
    assert row["category"] == "Travel"
    assert row["description"] == "Updated"


def test_delete_expense_removes_it(client, app):
    register(client)
    add_expense(client)
    assert count_expenses(app) == 1
    client.post("/expenses/1/delete", follow_redirects=True)
    assert count_expenses(app) == 0


# ------------------------------------------------------------------ #
# Ownership isolation — you can't touch another user's data           #
# ------------------------------------------------------------------ #

def test_cannot_edit_another_users_expense(client, app):
    register(client, email="a@example.com")        # user A (id 1)
    add_expense(client, amount="500", description="A's expense")  # expense id 1
    client.get("/logout")
    register(client, email="b@example.com")         # user B (id 2)

    client.post(
        "/expenses/1/edit",
        data={"amount": "1", "category": "Food",
              "description": "hacked", "spent_on": "2026-10-11"},
        follow_redirects=True,
    )
    with app.app_context():
        row = app_module.db.get_db().execute(
            "SELECT * FROM expenses WHERE id = 1"
        ).fetchone()
    assert row["amount"] == 500                      # untouched
    assert row["description"] == "A's expense"


def test_cannot_delete_another_users_expense(client, app):
    register(client, email="a@example.com")
    add_expense(client)
    client.get("/logout")
    register(client, email="b@example.com")

    client.post("/expenses/1/delete", follow_redirects=True)
    assert count_expenses(app) == 1                  # A's expense survived


# ------------------------------------------------------------------ #
# Profile / password change                                           #
# ------------------------------------------------------------------ #

def test_change_password_then_login_with_new_one(client):
    register(client)
    client.post(
        "/profile",
        data={"current_password": "password123", "new_password": "newpassword456"},
        follow_redirects=True,
    )
    client.get("/logout")
    r = login(client, password="newpassword456")
    assert b"Your expenses" in r.data


def test_change_password_wrong_current_is_rejected(client):
    register(client)
    r = client.post(
        "/profile",
        data={"current_password": "wrongone", "new_password": "newpassword456"},
        follow_redirects=True,
    )
    assert b"current password is incorrect" in r.data
