"""Spendwise — a small expense tracker built on Flask + SQLite.

The app is created by an application factory (``create_app``) so that tests
can spin up an isolated copy pointed at a throwaway database. Running this
file directly (``python app.py``) starts a development server on port 5001.
"""

import os
import sqlite3
import functools
from datetime import date, datetime

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, g, abort,
)
from werkzeug.security import generate_password_hash, check_password_hash

from database import db


# The fixed set of categories an expense can belong to. Keeping this in one
# place means the dropdown, validation, and dashboard all agree.
CATEGORIES = ["Food", "Travel", "Bills", "Shopping", "Health", "Entertainment", "Other"]


# ------------------------------------------------------------------ #
# Auth helpers                                                        #
# ------------------------------------------------------------------ #

def login_required(view):
    """Decorator: bounce anonymous visitors to the login page.

    Wrap any view that should only be reachable when signed in.
    """
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if session.get("user_id") is None:
            flash("Please sign in to continue.", "error")
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def current_user():
    """Return the logged-in user's row, or None. Cached per request on g."""
    if "user" not in g:
        user_id = session.get("user_id")
        if user_id is None:
            g.user = None
        else:
            g.user = db.get_db().execute(
                "SELECT id, name, email, created_at FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
            # Session points at a user that no longer exists -> treat as logged out.
            if g.user is None:
                session.clear()
    return g.user


def _validate_expense(form):
    """Validate and normalise an expense form submission.

    Returns ``(data, error)`` where ``data`` is a dict safe to insert and
    ``error`` is a human-readable string (or None when everything is valid).
    ``data`` is always fully populated so templates can re-render the form.
    """
    amount_raw = form.get("amount", "").strip()
    category = form.get("category", "").strip()
    description = form.get("description", "").strip()
    spent_on = form.get("spent_on", "").strip()

    error = None
    amount = None
    try:
        amount = round(float(amount_raw), 2)
        if amount <= 0:
            error = "Amount must be greater than zero."
    except ValueError:
        error = "Amount must be a valid number."

    if error is None and category not in CATEGORIES:
        error = "Please choose a valid category."

    if error is None:
        try:
            datetime.strptime(spent_on, "%Y-%m-%d")
        except ValueError:
            error = "Please provide a valid date."

    data = {
        "amount": amount if amount is not None else amount_raw,
        "category": category,
        "description": description,
        "spent_on": spent_on,
    }
    return data, error


# ------------------------------------------------------------------ #
# Application factory                                                 #
# ------------------------------------------------------------------ #

def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_mapping(
        # Signs the session cookie. Override with a real secret in production.
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-secret-change-me"),
        DATABASE=os.path.join(app.root_path, "database", "expense_tracker.db"),
    )
    if test_config:
        app.config.update(test_config)

    # Wire up the database (teardown hook) and make sure the tables exist.
    db.init_app(app)
    with app.app_context():
        db.init_db()

    # Expose the current user to every template (so base.html can switch nav).
    @app.context_processor
    def inject_user():
        return {"current_user": current_user()}

    # -------------------------------------------------------------- #
    # Public pages                                                   #
    # -------------------------------------------------------------- #

    @app.route("/")
    def landing():
        if session.get("user_id"):
            return redirect(url_for("dashboard"))
        return render_template("landing.html")

    @app.route("/terms")
    def terms():
        return render_template("terms.html")

    @app.route("/privacy")
    def privacy():
        return render_template("privacy.html")

    # -------------------------------------------------------------- #
    # Step 2/3 — Authentication (register, login, logout)            #
    # -------------------------------------------------------------- #

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if session.get("user_id"):
            return redirect(url_for("dashboard"))

        if request.method == "POST":
            name = request.form.get("name", "").strip()
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")

            error = None
            if not name or not email or not password:
                error = "All fields are required."
            elif len(password) < 8:
                error = "Password must be at least 8 characters."

            if error is None:
                conn = db.get_db()
                try:
                    conn.execute(
                        "INSERT INTO users (name, email, password_hash) "
                        "VALUES (?, ?, ?)",
                        (name, email, generate_password_hash(password)),
                    )
                    conn.commit()
                except sqlite3.IntegrityError:
                    error = "An account with that email already exists."
                else:
                    user = conn.execute(
                        "SELECT id FROM users WHERE email = ?", (email,)
                    ).fetchone()
                    session.clear()
                    session["user_id"] = user["id"]
                    flash("Welcome to Spendwise! Your account is ready.", "success")
                    return redirect(url_for("dashboard"))

            return render_template("register.html", error=error, name=name, email=email)

        return render_template("register.html")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if session.get("user_id"):
            return redirect(url_for("dashboard"))

        if request.method == "POST":
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")

            user = db.get_db().execute(
                "SELECT * FROM users WHERE email = ?", (email,)
            ).fetchone()

            # Same generic message whether the email or the password is wrong,
            # so we don't reveal which emails have accounts.
            if user is None or not check_password_hash(user["password_hash"], password):
                return render_template(
                    "login.html", error="Invalid email or password.", email=email
                )

            session.clear()
            session["user_id"] = user["id"]
            flash("Signed in successfully.", "success")

            # Honour ?next=... but only for local paths (no open redirects).
            next_page = request.args.get("next", "")
            if next_page.startswith("/") and not next_page.startswith("//"):
                return redirect(next_page)
            return redirect(url_for("dashboard"))

        return render_template("login.html")

    @app.route("/logout")
    def logout():
        session.clear()
        flash("You have been signed out.", "success")
        return redirect(url_for("landing"))

    # -------------------------------------------------------------- #
    # Step 4 — Profile                                               #
    # -------------------------------------------------------------- #

    @app.route("/profile", methods=["GET", "POST"])
    @login_required
    def profile():
        conn = db.get_db()
        user_id = session["user_id"]

        if request.method == "POST":
            current = request.form.get("current_password", "")
            new = request.form.get("new_password", "")
            row = conn.execute(
                "SELECT password_hash FROM users WHERE id = ?", (user_id,)
            ).fetchone()

            if not check_password_hash(row["password_hash"], current):
                flash("Your current password is incorrect.", "error")
            elif len(new) < 8:
                flash("New password must be at least 8 characters.", "error")
            else:
                conn.execute(
                    "UPDATE users SET password_hash = ? WHERE id = ?",
                    (generate_password_hash(new), user_id),
                )
                conn.commit()
                flash("Password updated.", "success")
            return redirect(url_for("profile"))

        user = conn.execute(
            "SELECT id, name, email, created_at FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        stats = conn.execute(
            "SELECT COUNT(*) AS count, COALESCE(SUM(amount), 0) AS total "
            "FROM expenses WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        return render_template("profile.html", user=user, stats=stats)

    # -------------------------------------------------------------- #
    # Steps 5/6 — Dashboard (list + summary)                         #
    # -------------------------------------------------------------- #

    @app.route("/dashboard")
    @login_required
    def dashboard():
        conn = db.get_db()
        user_id = session["user_id"]

        expenses = conn.execute(
            "SELECT * FROM expenses WHERE user_id = ? "
            "ORDER BY spent_on DESC, id DESC",
            (user_id,),
        ).fetchall()

        total = sum(e["amount"] for e in expenses)

        # Per-category totals, biggest first, for the breakdown bars.
        by_category = conn.execute(
            "SELECT category, SUM(amount) AS total, COUNT(*) AS count "
            "FROM expenses WHERE user_id = ? "
            "GROUP BY category ORDER BY total DESC",
            (user_id,),
        ).fetchall()

        return render_template(
            "dashboard.html",
            expenses=expenses,
            total=total,
            by_category=by_category,
            grand_total=total,
        )

    # -------------------------------------------------------------- #
    # Steps 7/8/9 — Add, edit, delete an expense                     #
    # -------------------------------------------------------------- #

    @app.route("/expenses/add", methods=["GET", "POST"])
    @login_required
    def add_expense():
        if request.method == "POST":
            data, error = _validate_expense(request.form)
            if error:
                return render_template(
                    "expense_form.html", mode="add", error=error,
                    expense=data, categories=CATEGORIES,
                )
            conn = db.get_db()
            conn.execute(
                "INSERT INTO expenses (user_id, amount, category, description, spent_on) "
                "VALUES (?, ?, ?, ?, ?)",
                (session["user_id"], data["amount"], data["category"],
                 data["description"], data["spent_on"]),
            )
            conn.commit()
            flash("Expense added.", "success")
            return redirect(url_for("dashboard"))

        # GET: blank form, defaulting the date to today.
        expense = {"amount": "", "category": "", "description": "",
                   "spent_on": date.today().isoformat()}
        return render_template(
            "expense_form.html", mode="add", expense=expense, categories=CATEGORIES
        )

    @app.route("/expenses/<int:id>/edit", methods=["GET", "POST"])
    @login_required
    def edit_expense(id):
        conn = db.get_db()
        # The "AND user_id" clause is the ownership check: you can only ever
        # load (and therefore edit) your own expenses.
        expense = conn.execute(
            "SELECT * FROM expenses WHERE id = ? AND user_id = ?",
            (id, session["user_id"]),
        ).fetchone()
        if expense is None:
            abort(404)

        if request.method == "POST":
            data, error = _validate_expense(request.form)
            if error:
                data["id"] = id
                return render_template(
                    "expense_form.html", mode="edit", error=error,
                    expense=data, categories=CATEGORIES,
                )
            conn.execute(
                "UPDATE expenses SET amount = ?, category = ?, description = ?, "
                "spent_on = ? WHERE id = ? AND user_id = ?",
                (data["amount"], data["category"], data["description"],
                 data["spent_on"], id, session["user_id"]),
            )
            conn.commit()
            flash("Expense updated.", "success")
            return redirect(url_for("dashboard"))

        return render_template(
            "expense_form.html", mode="edit", expense=expense, categories=CATEGORIES
        )

    @app.route("/expenses/<int:id>/delete", methods=["POST"])
    @login_required
    def delete_expense(id):
        conn = db.get_db()
        # DELETE scoped to the owner: a crafted id for someone else's expense
        # simply matches zero rows.
        cursor = conn.execute(
            "DELETE FROM expenses WHERE id = ? AND user_id = ?",
            (id, session["user_id"]),
        )
        conn.commit()
        if cursor.rowcount:
            flash("Expense deleted.", "success")
        else:
            flash("That expense could not be found.", "error")
        return redirect(url_for("dashboard"))

    # -------------------------------------------------------------- #
    # Error handlers                                                 #
    # -------------------------------------------------------------- #

    @app.errorhandler(404)
    def not_found(error):
        return render_template("error.html", code=404,
                               message="We couldn't find that page."), 404

    # Make the category list available to templates that need it.
    @app.context_processor
    def inject_categories():
        return {"CATEGORIES": CATEGORIES}

    # Format a number as rupees, e.g. 1499.5 -> "₹1,499.50".
    @app.template_filter("rupees")
    def rupees(value):
        try:
            return "₹{:,.2f}".format(float(value))
        except (ValueError, TypeError):
            return "₹0.00"

    # Format an ISO date (YYYY-MM-DD) as "12 Oct 2026"; pass through on failure.
    @app.template_filter("prettydate")
    def prettydate(value):
        try:
            return datetime.strptime(str(value), "%Y-%m-%d").strftime("%d %b %Y")
        except (ValueError, TypeError):
            return value

    return app


# A module-level app so `python app.py` and WSGI servers both work.
app = create_app()


if __name__ == "__main__":
    # On a fresh database, drop in demo data so there's something to look at,
    # and print the login so you can sign in immediately.
    with app.app_context():
        creds = db.seed_db()
    if creds:
        print("\n  Seeded a demo account:")
        print(f"    email:    {creds['email']}")
        print(f"    password: {creds['password']}\n")
    app.run(debug=True, port=5001)
