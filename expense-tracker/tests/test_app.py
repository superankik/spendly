"""End-to-end tests for Spendwise using Flask's test client."""


def _add_expense(client, amount="250", category="Food",
                 description="Lunch", spent_on="2026-10-10"):
    return client.post("/expenses/add", data={
        "amount": amount, "category": category,
        "description": description, "spent_on": spent_on,
    })


# --- Public pages -------------------------------------------------- #

def test_landing_page(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"Spendwise" in resp.data


def test_404_page(client):
    resp = client.get("/no-such-page")
    assert resp.status_code == 404
    assert b"404" in resp.data
    assert b"find that page" in resp.data


# --- Registration -------------------------------------------------- #

def test_register_logs_in_and_redirects(client, auth):
    resp = auth.register()
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/dashboard")
    # Now authenticated: dashboard is reachable.
    assert client.get("/dashboard").status_code == 200


def test_register_requires_all_fields(client):
    resp = client.post("/register", data={"name": "", "email": "", "password": ""})
    assert resp.status_code == 200
    assert b"All fields are required." in resp.data


def test_register_rejects_short_password(client):
    resp = client.post("/register", data={
        "name": "A", "email": "a@b.com", "password": "short",
    })
    assert b"at least 8 characters" in resp.data


def test_register_rejects_duplicate_email(client, auth):
    auth.register()
    auth.logout()
    resp = auth.register()  # same email again
    assert b"already exists" in resp.data


# --- Login / logout ------------------------------------------------ #

def test_login_with_valid_credentials(client, auth):
    auth.register()
    auth.logout()
    resp = auth.login()
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/dashboard")


def test_login_with_invalid_credentials(client, auth):
    auth.register()
    auth.logout()
    resp = auth.login(password="wrong-password")
    assert resp.status_code == 200
    assert b"Invalid email or password." in resp.data


def test_logout_clears_session(client, auth):
    auth.register()
    auth.logout()
    resp = client.get("/dashboard")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


# --- Access control ------------------------------------------------ #

def test_dashboard_requires_login(client):
    resp = client.get("/dashboard")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_profile_requires_login(client):
    resp = client.get("/profile")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


# --- Expense CRUD -------------------------------------------------- #

def test_add_expense_shows_on_dashboard(client, auth):
    auth.register()
    resp = _add_expense(client, amount="250", description="Team lunch")
    assert resp.status_code == 302
    dash = client.get("/dashboard")
    assert b"Team lunch" in dash.data
    assert b"250.00" in dash.data


def test_add_expense_rejects_bad_amount(client, auth):
    auth.register()
    resp = _add_expense(client, amount="not-a-number")
    assert resp.status_code == 200
    assert b"valid number" in resp.data


def test_add_expense_rejects_unknown_category(client, auth):
    auth.register()
    resp = _add_expense(client, category="Crypto")
    assert resp.status_code == 200
    assert b"valid category" in resp.data


def test_edit_expense_updates_values(client, auth):
    auth.register()
    _add_expense(client)
    resp = client.post("/expenses/1/edit", data={
        "amount": "300", "category": "Travel",
        "description": "Cab ride", "spent_on": "2026-10-11",
    })
    assert resp.status_code == 302
    dash = client.get("/dashboard")
    assert b"Cab ride" in dash.data
    assert b"300.00" in dash.data


def test_delete_expense_removes_it(client, auth):
    auth.register()
    _add_expense(client)
    resp = client.post("/expenses/1/delete")
    assert resp.status_code == 302
    dash = client.get("/dashboard")
    assert b"No expenses yet" in dash.data


def test_delete_rejects_get(client, auth):
    auth.register()
    _add_expense(client)
    resp = client.get("/expenses/1/delete")
    assert resp.status_code == 405  # method not allowed


# --- Ownership: you cannot touch someone else's data --------------- #

def test_cannot_edit_another_users_expense(client, auth):
    auth.register(email="alice@example.com")
    _add_expense(client, description="Alice lunch")
    auth.logout()
    auth.register(name="Bob", email="bob@example.com")
    # GET and POST both 404 for an expense Bob doesn't own.
    assert client.get("/expenses/1/edit").status_code == 404
    resp = client.post("/expenses/1/edit", data={
        "amount": "999", "category": "Food",
        "description": "hijacked", "spent_on": "2026-10-10",
    })
    assert resp.status_code == 404


def test_cannot_delete_another_users_expense(client, auth):
    auth.register(email="alice@example.com")
    _add_expense(client, description="Alice keeps this")
    auth.logout()
    auth.register(name="Bob", email="bob@example.com")
    client.post("/expenses/1/delete")  # no-op for Bob
    auth.logout()
    auth.login(email="alice@example.com")
    dash = client.get("/dashboard")
    assert b"Alice keeps this" in dash.data  # still there


# --- Profile ------------------------------------------------------- #

def test_profile_shows_user_details(client, auth):
    auth.register(name="Jane Doe", email="jane@example.com")
    resp = client.get("/profile")
    assert resp.status_code == 200
    assert b"jane@example.com" in resp.data


def test_change_password(client, auth):
    auth.register()
    resp = client.post("/profile", data={
        "current_password": "password123",
        "new_password": "brand-new-pass",
    }, follow_redirects=True)
    assert b"Password updated." in resp.data
    auth.logout()
    # Old password no longer works, new one does.
    assert auth.login(password="password123").status_code == 200
    assert auth.login(password="brand-new-pass").status_code == 302


def test_change_password_wrong_current(client, auth):
    auth.register()
    resp = client.post("/profile", data={
        "current_password": "WRONG",
        "new_password": "brand-new-pass",
    }, follow_redirects=True)
    assert b"current password is incorrect" in resp.data
