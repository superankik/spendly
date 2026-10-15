"""Spendly — a small expense tracker built on Flask + SQLite.

Route map
---------
    /                     landing page (redirects to /dashboard when logged in)
    /register             create an account                 [GET, POST]
    /login                sign in                            [GET, POST]
    /logout               sign out                           [GET]
    /dashboard            list + summary of your expenses    [GET]   (auth)
    /expenses/add         add an expense                     [GET, POST] (auth)
    /expenses/<id>/edit   edit one of your expenses          [GET, POST] (auth)
    /expenses/<id>/delete delete one of your expenses        [POST]  (auth)
    /profile              your account + change password     [GET, POST] (auth)
    /terms, /privacy      static legal pages                 [GET]
"""

import functools
import os
import sqlite3
from datetime import date, datetime

from flask import (
    Flask, flash, g, redirect, render_template, request, session, url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

from database import db

# ------------------------------------------------------------------ #
# App setup                                                           #
# ------------------------------------------------------------------ #

app = Flask(__name__)

# Sessions are signed with this key. In production set a real secret via the
# SECRET_KEY environment variable; the fallback is only for local dev.
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me")

# The SQLite file lives next to the code, inside database/. It's git-ignored.
app.config["DATABASE"] = os.path.join(app.root_path, "database", "expense_tracker.db")

# Fixed set of categories the UI offers. Keeping it a constant means the
# dropdown, validation, and dashboard colours all agree.
CATEGORIES = ["Food", "Travel", "Bills", "Shopping", "Health", "Entertainment", "Other"]

db.init_app(app)

# Create the tables on startup, and seed sample data the very first time the
# database file is created (so a fresh checkout has something to look at).
with app.app_context():
    _db_existed = os.path.exists(app.config["DATABASE"])
    db.init_db()
    if not _db_existed:
        db.seed_db()


# ------------------------------------------------------------------ #
# Auth helpers                                                        #
# ------------------------------------------------------------------ #

@app.before_request
def load_logged_in_user():
    """Load the current user into ``g`` at the start of every request.

    Doing this per-request (rather than caching lazily) keeps ``g.user`` in
    step with the session even when several requests share one application
    context, which is how the Flask tutorial recommends it.
    """
    user_id = session.get("user_id")
    if user_id is None:
        g.user = None
    else:
        g.user = db.get_db().execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ).fetchone()


def current_user():
    """Return the row for the logged-in user, or None if anonymous."""
    return g.get("user")


def login_required(view):
    """Decorator: bounce anonymous visitors to the login page."""
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if current_user() is None:
            flash("Please sign in to continue.", "error")
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


@app.context_processor
def inject_user():
    """Make `current_user` available to every template (used by the navbar)."""
    return {"current_user": current_user()}


@app.template_filter("rupees")
def rupees(value):
    """Format a number as a rupee amount, e.g. 1234.5 -> '₹1,234.50'."""
    try:
        return "₹{:,.2f}".format(float(value))
    except (TypeError, ValueError):
        return value


def _safe_next(target):
    """Only allow redirects to local paths (prevents open-redirect abuse)."""
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return None


# ------------------------------------------------------------------ #
# Public pages                                                        #
# ------------------------------------------------------------------ #

@app.route("/")
def landing():
    if current_user() is not None:
        return redirect(url_for("dashboard"))
    return render_template("landing.html")


@app.route("/terms")
def terms():
    return render_template("terms.html")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


# ------------------------------------------------------------------ #
# Step 2 — Register                                                   #
# ------------------------------------------------------------------ #

@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user() is not None:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        error = None
        if not name:
            error = "Please enter your name."
        elif not email:
            error = "Please enter your email."
        elif len(password) < 8:
            error = "Password must be at least 8 characters."

        if error is None:
            conn = db.get_db()
            try:
                cur = conn.execute(
                    "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
                    (name, email, generate_password_hash(password)),
                )
                conn.commit()
            except sqlite3.IntegrityError:
                error = "That email is already registered."
            else:
                # Log the new user straight in.
                session.clear()
                session["user_id"] = cur.lastrowid
                flash(f"Welcome to Spendly, {name.split()[0]}!", "success")
                return redirect(url_for("dashboard"))

        return render_template("register.html", error=error)

    return render_template("register.html")


# ------------------------------------------------------------------ #
# Step 3 — Login / Logout                                             #
# ------------------------------------------------------------------ #

@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user() is not None:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        user = db.get_db().execute(
            "SELECT * FROM users WHERE email = ?", (email,)
        ).fetchone()

        # One generic message for both cases — don't reveal which emails exist.
        if user is None or not check_password_hash(user["password_hash"], password):
            return render_template("login.html", error="Incorrect email or password.")

        session.clear()
        session["user_id"] = user["id"]
        flash("Signed in successfully.", "success")
        return redirect(_safe_next(request.args.get("next")) or url_for("dashboard"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You've been signed out.", "success")
    return redirect(url_for("landing"))


# ------------------------------------------------------------------ #
# Step 4 — Profile                                                    #
# ------------------------------------------------------------------ #

@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    user = current_user()
    conn = db.get_db()

    if request.method == "POST":
        current = request.form.get("current_password", "")
        new = request.form.get("new_password", "")

        if not check_password_hash(user["password_hash"], current):
            flash("Your current password is incorrect.", "error")
        elif len(new) < 8:
            flash("New password must be at least 8 characters.", "error")
        else:
            conn.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (generate_password_hash(new), user["id"]),
            )
            conn.commit()
            flash("Password updated.", "success")
        return redirect(url_for("profile"))

    # A couple of lifetime stats for the profile page.
    stats = conn.execute(
        "SELECT COUNT(*) AS count, COALESCE(SUM(amount), 0) AS total "
        "FROM expenses WHERE user_id = ?",
        (user["id"],),
    ).fetchone()
    return render_template("profile.html", stats=stats)


# ------------------------------------------------------------------ #
# Steps 5-6 — Dashboard (list + summary)                              #
# ------------------------------------------------------------------ #

@app.route("/dashboard")
@login_required
def dashboard():
    user = current_user()
    expenses = db.get_db().execute(
        "SELECT * FROM expenses WHERE user_id = ? ORDER BY spent_on DESC, id DESC",
        (user["id"],),
    ).fetchall()

    total = sum(e["amount"] for e in expenses)

    # This calendar month's spending + transaction count.
    this_month = date.today().strftime("%Y-%m")
    month_rows = [e for e in expenses if e["spent_on"].startswith(this_month)]
    month_total = sum(e["amount"] for e in month_rows)

    # Spend per category, biggest first, with a bar width relative to the top.
    by_cat = {}
    for e in expenses:
        by_cat[e["category"]] = by_cat.get(e["category"], 0) + e["amount"]
    top = max(by_cat.values(), default=0)
    categories = [
        {"name": name, "total": amt, "pct": round(amt / top * 100) if top else 0}
        for name, amt in sorted(by_cat.items(), key=lambda kv: kv[1], reverse=True)
    ]

    return render_template(
        "dashboard.html",
        expenses=expenses,
        total=total,
        month_total=month_total,
        month_count=len(month_rows),
        categories=categories,
    )


# ------------------------------------------------------------------ #
# Expense form parsing (shared by add + edit)                         #
# ------------------------------------------------------------------ #

def _parse_expense_form(form):
    """Validate the add/edit form. Returns (data_dict, error_message)."""
    amount_raw = form.get("amount", "").strip()
    category = form.get("category", "").strip()
    description = form.get("description", "").strip()
    spent_on = form.get("spent_on", "").strip()

    try:
        amount = float(amount_raw)
    except ValueError:
        return None, "Amount must be a number."
    if amount <= 0:
        return None, "Amount must be greater than zero."

    if category not in CATEGORIES:
        return None, "Please choose a valid category."

    try:
        datetime.strptime(spent_on, "%Y-%m-%d")
    except ValueError:
        return None, "Please choose a valid date."

    if len(description) > 200:
        return None, "Description is too long (200 characters max)."

    return {
        "amount": round(amount, 2),
        "category": category,
        "description": description,
        "spent_on": spent_on,
    }, None


def _owned_expense_or_none(expense_id, user_id):
    """Fetch an expense only if it belongs to this user."""
    return db.get_db().execute(
        "SELECT * FROM expenses WHERE id = ? AND user_id = ?",
        (expense_id, user_id),
    ).fetchone()


# ------------------------------------------------------------------ #
# Step 7 — Add expense                                                #
# ------------------------------------------------------------------ #

@app.route("/expenses/add", methods=["GET", "POST"])
@login_required
def add_expense():
    user = current_user()

    if request.method == "POST":
        data, error = _parse_expense_form(request.form)
        if error:
            flash(error, "error")
            return render_template(
                "expense_form.html", mode="add", categories=CATEGORIES,
                expense=request.form,
            )
        conn = db.get_db()
        conn.execute(
            "INSERT INTO expenses (user_id, amount, category, description, spent_on) "
            "VALUES (?, ?, ?, ?, ?)",
            (user["id"], data["amount"], data["category"],
             data["description"], data["spent_on"]),
        )
        conn.commit()
        flash("Expense added.", "success")
        return redirect(url_for("dashboard"))

    # Blank form, defaulting the date to today.
    return render_template(
        "expense_form.html", mode="add", categories=CATEGORIES,
        expense={"spent_on": date.today().isoformat()},
    )


# ------------------------------------------------------------------ #
# Step 8 — Edit expense                                               #
# ------------------------------------------------------------------ #

@app.route("/expenses/<int:id>/edit", methods=["GET", "POST"])
@login_required
def edit_expense(id):
    user = current_user()
    expense = _owned_expense_or_none(id, user["id"])
    if expense is None:
        flash("That expense doesn't exist.", "error")
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        data, error = _parse_expense_form(request.form)
        if error:
            flash(error, "error")
            # Re-show the form with what they typed, keeping the id.
            form = dict(request.form)
            form["id"] = id
            return render_template(
                "expense_form.html", mode="edit", categories=CATEGORIES,
                expense=form,
            )
        conn = db.get_db()
        conn.execute(
            "UPDATE expenses SET amount = ?, category = ?, description = ?, "
            "spent_on = ? WHERE id = ? AND user_id = ?",
            (data["amount"], data["category"], data["description"],
             data["spent_on"], id, user["id"]),
        )
        conn.commit()
        flash("Expense updated.", "success")
        return redirect(url_for("dashboard"))

    return render_template(
        "expense_form.html", mode="edit", categories=CATEGORIES, expense=expense,
    )


# ------------------------------------------------------------------ #
# Step 9 — Delete expense                                             #
# ------------------------------------------------------------------ #

@app.route("/expenses/<int:id>/delete", methods=["POST"])
@login_required
def delete_expense(id):
    user = current_user()
    conn = db.get_db()
    # The user_id clause makes it impossible to delete someone else's row.
    conn.execute(
        "DELETE FROM expenses WHERE id = ? AND user_id = ?", (id, user["id"])
    )
    conn.commit()
    flash("Expense deleted.", "success")
    return redirect(url_for("dashboard"))


if __name__ == "__main__":
    # Port defaults to 5001 but can be overridden, e.g. `PORT=5002 python app.py`.
    app.run(debug=True, port=int(os.environ.get("PORT", "5001")))
