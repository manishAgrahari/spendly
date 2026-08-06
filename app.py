import sqlite3
from datetime import datetime

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


def _get_recent_transactions(user_id, limit=10, start_date=None, end_date=None):
    conn = get_db()

    clauses = ["user_id = ?"]
    params = [user_id]
    if start_date:
        clauses.append("date >= ?")
        params.append(start_date)
    if end_date:
        clauses.append("date <= ?")
        params.append(end_date)
    params.append(limit)

    rows = conn.execute(
        f"""
        SELECT date, COALESCE(description, '') AS description, category, amount
        FROM expenses
        WHERE {' AND '.join(clauses)}
        ORDER BY date DESC, id DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    conn.close()
    return rows


def _get_summary_stats(user_id, start_date=None, end_date=None):
    conn = get_db()

    clauses = ["user_id = ?"]
    params = [user_id]
    if start_date:
        clauses.append("date >= ?")
        params.append(start_date)
    if end_date:
        clauses.append("date <= ?")
        params.append(end_date)
    where_sql = " AND ".join(clauses)

    total_row = conn.execute(
        f"""
        SELECT COALESCE(SUM(amount),0) AS total, COUNT(*) AS count
        FROM expenses
        WHERE {where_sql}
        """,
        params,
    ).fetchone()

    top_category_row = conn.execute(
        f"SELECT category FROM expenses WHERE {where_sql} "
        "GROUP BY category ORDER BY SUM(amount) DESC, category ASC LIMIT 1",
        params,
    ).fetchone()

    conn.close()

    top_category = top_category_row["category"] if top_category_row else "No expenses yet"

    return {
        "total_spent": total_row["total"],
        "transaction_count": total_row["count"],
        "top_category": top_category,
    }


def _get_category_breakdown(user_id, total_spent, start_date=None, end_date=None):
    conn = get_db()

    clauses = ["user_id = ?"]
    params = [user_id]
    if start_date:
        clauses.append("date >= ?")
        params.append(start_date)
    if end_date:
        clauses.append("date <= ?")
        params.append(end_date)

    rows = conn.execute(
        f"""
        SELECT category AS name, SUM(amount) AS amount
        FROM expenses
        WHERE {' AND '.join(clauses)}
        GROUP BY category
        ORDER BY amount DESC, category ASC
        """,
        params,
    ).fetchall()
    conn.close()

    return [
        {
            "name": row["name"],
            "amount": row["amount"],
            "percent": round(row["amount"] / total_spent * 100) if total_spent else 0,
        }
        for row in rows
    ]


@app.route("/profile")
def profile():
    if not session.get("user_id"):
        return redirect(url_for("login"))

    user_id = session["user_id"]

    start_date_raw = request.args.get("start_date", "").strip()
    end_date_raw = request.args.get("end_date", "").strip()

    start_date = None
    end_date = None
    try:
        if start_date_raw:
            datetime.strptime(start_date_raw, "%Y-%m-%d")
            start_date = start_date_raw
        if end_date_raw:
            datetime.strptime(end_date_raw, "%Y-%m-%d")
            end_date = end_date_raw
    except ValueError:
        start_date = None
        end_date = None

    if start_date and end_date and start_date > end_date:
        start_date = None
        end_date = None

    conn = get_db()
    user_row = conn.execute(
        "SELECT name, email, created_at FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    conn.close()

    created_at = datetime.strptime(user_row["created_at"], "%Y-%m-%d %H:%M:%S")
    name_parts = user_row["name"].split()
    initials = "".join(part[0] for part in name_parts[:2]).upper()

    user = {
        "name": user_row["name"],
        "email": user_row["email"],
        "member_since": created_at.strftime("%B %Y"),
        "initials": initials,
    }

    stats = _get_summary_stats(user_id, start_date=start_date, end_date=end_date)
    transactions = _get_recent_transactions(user_id, start_date=start_date, end_date=end_date)
    categories = _get_category_breakdown(
        user_id, stats["total_spent"], start_date=start_date, end_date=end_date
    )

    return render_template(
        "profile.html",
        user=user,
        stats=stats,
        transactions=transactions,
        categories=categories,
        start_date=start_date,
        end_date=end_date,
    )


@app.route("/analytics")
def analytics():
    if not session.get("user_id"):
        return redirect(url_for("login"))
    return render_template("analytics.html")


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
