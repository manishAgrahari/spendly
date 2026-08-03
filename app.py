import sqlite3

from flask import Flask, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from database.db import get_db, init_db, seed_db

app = Flask(__name__)
app.config["SECRET_KEY"] = "spendly-dev-secret-key"  # local/dev only — not for production

# Used to check against when no matching user is found, so a missing email and
# a wrong password take the same amount of work and never crash on None.
_DUMMY_PASSWORD_HASH = generate_password_hash("not-a-real-password")

with app.app_context():
    init_db()
    seed_db()


# ------------------------------------------------------------------ #
# Routes                                                              #
# ------------------------------------------------------------------ #

@app.route("/")
def landing():
    return render_template("landing.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return render_template("register.html")

    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")

    if not name or not email or not password:
        return render_template("register.html", error="All fields are required.")

    if len(password) < 8:
        return render_template(
            "register.html", error="Password must be at least 8 characters long."
        )

    password_hash = generate_password_hash(password)

    conn = get_db()
    try:
        cursor = conn.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            (name, email, password_hash),
        )
        conn.commit()
        user_id = cursor.lastrowid
    except sqlite3.IntegrityError:
        conn.rollback()
        return render_template(
            "register.html", error="An account with this email already exists."
        )
    finally:
        conn.close()

    session["user_id"] = user_id
    return redirect(url_for("landing"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")

    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")

    conn = get_db()
    user = conn.execute(
        "SELECT id, password_hash FROM users WHERE email = ?", (email,)
    ).fetchone()
    conn.close()

    hash_to_check = user["password_hash"] if user else _DUMMY_PASSWORD_HASH
    password_ok = check_password_hash(hash_to_check, password)

    if user is None or not password_ok:
        return render_template("login.html", error="Invalid email or password.")

    session["user_id"] = user["id"]
    return redirect(url_for("profile"))


@app.route("/terms")
def terms():
    return render_template("terms.html")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


# ------------------------------------------------------------------ #
# Placeholder routes — students will implement these                  #
# ------------------------------------------------------------------ #

@app.route("/logout")
def logout():
    session.pop("user_id", None)
    return redirect(url_for("landing"))


@app.route("/profile")
def profile():
    if not session.get("user_id"):
        return redirect(url_for("login"))

    user = {
        "name": "Demo User",
        "email": "demo@spendly.com",
        "member_since": "March 2026",
        "initials": "DU",
    }

    stats = {
        "total_spent": 423.44,
        "transaction_count": 8,
        "top_category": "Shopping",
    }

    transactions = [
        {"date": "2026-08-01", "description": "Groceries", "category": "Food", "amount": 12.50},
        {"date": "2026-07-29", "description": "Monthly transit pass", "category": "Transport", "amount": 45.00},
        {"date": "2026-07-27", "description": "Electricity bill", "category": "Bills", "amount": 89.99},
        {"date": "2026-07-24", "description": "Movie night", "category": "Entertainment", "amount": 60.00},
        {"date": "2026-07-21", "description": "New shoes", "category": "Shopping", "amount": 150.00},
    ]

    categories = [
        {"name": "Shopping", "amount": 150.00, "percent": 35},
        {"name": "Bills", "amount": 89.99, "percent": 21},
        {"name": "Entertainment", "amount": 60.00, "percent": 14},
        {"name": "Transport", "amount": 45.00, "percent": 11},
        {"name": "Food", "amount": 12.50, "percent": 3},
    ]

    return render_template(
        "profile.html",
        user=user,
        stats=stats,
        transactions=transactions,
        categories=categories,
    )


@app.route("/expenses/add")
def add_expense():
    return "Add expense — coming in Step 7"


@app.route("/expenses/<int:id>/edit")
def edit_expense(id):
    return "Edit expense — coming in Step 8"


@app.route("/expenses/<int:id>/delete")
def delete_expense(id):
    return "Delete expense — coming in Step 9"


if __name__ == "__main__":
    app.run(debug=True, port=5001)
