"""
Tests for the "Date Filter for Profile Page" feature.

Spec: .claude/specs/06-date-filter-profile-page.md

`GET /profile` accepts optional `start_date` / `end_date` query params
(`YYYY-MM-DD`). When both are valid, `stats`, `transactions`, and
`categories` are scoped to expenses whose `date` falls in that inclusive
range. Either date may be supplied alone (open-ended range). Malformed
dates, or a start_date after end_date, must fall back to the all-time
(unfiltered) view without crashing. The auth guard on `/profile` is
unchanged, and the date filter must never widen the query scope beyond
the logged-in user's own expenses.

These tests exercise the route purely through the Flask test client and
verify behaviour via:
  - HTTP status codes / redirect targets
  - the actual `stats` / `transactions` / `categories` context passed to
    `profile.html`, captured via Flask's `template_rendered` signal
    (avoids depending on the template's HTML structure, which is out of
    scope for this test file)

Because `database.db.get_db()` connects to a module-level `DB_PATH`
constant (not a Flask config key), isolation is achieved by monkeypatching
`database.db.DB_PATH` to a per-test temp file before `init_db()` runs.
"""

from contextlib import contextmanager

import pytest
from flask import template_rendered, url_for
from werkzeug.security import generate_password_hash

import database.db as db_module
from app import app as flask_app
from database.db import get_db, init_db

DEFAULT_PASSWORD = "password123"


# --------------------------------------------------------------------- #
# Fixtures                                                               #
# --------------------------------------------------------------------- #

@pytest.fixture
def app(tmp_path, monkeypatch):
    """Flask app wired to an isolated, empty, per-test SQLite file."""
    test_db_path = tmp_path / "test_expense_tracker.db"
    monkeypatch.setattr(db_module, "DB_PATH", test_db_path)

    flask_app.config.update(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
        }
    )

    with flask_app.app_context():
        init_db()

    yield flask_app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def auth_client(client):
    """A test client logged in as a fresh 'owner' user.

    The authenticated user's id is stashed as `.user_id` on the returned
    client for convenience when seeding expenses directly via the DB.
    """
    user_id = _register_and_login(client, email="owner@example.com")
    client.user_id = user_id
    return client


# --------------------------------------------------------------------- #
# Helpers                                                                #
# --------------------------------------------------------------------- #

def _register_and_login(client, email, name="Test User", password=DEFAULT_PASSWORD):
    client.post(
        "/register",
        data={"name": name, "email": email, "password": password},
    )
    client.post(
        "/login",
        data={"email": email, "password": password},
    )
    with client.session_transaction() as sess:
        user_id = sess.get("user_id")
    assert user_id is not None, "Expected session['user_id'] to be set after register+login"
    return user_id


def _create_other_user(app, email, name="Other User", password=DEFAULT_PASSWORD):
    """Create a user directly in the DB without logging in as them."""
    with app.app_context():
        conn = get_db()
        cursor = conn.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            (name, email, generate_password_hash(password)),
        )
        conn.commit()
        user_id = cursor.lastrowid
        conn.close()
    return user_id


def _insert_expense(app, user_id, amount, category, expense_date, description=""):
    with app.app_context():
        conn = get_db()
        conn.execute(
            """
            INSERT INTO expenses (user_id, amount, category, date, description)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, amount, category, expense_date, description),
        )
        conn.commit()
        conn.close()


@contextmanager
def captured_templates(app):
    """Capture (template, context) pairs rendered during the `with` block."""
    recorded = []

    def record(sender, template, context, **extra):
        recorded.append((template, context))

    template_rendered.connect(record, app)
    try:
        yield recorded
    finally:
        template_rendered.disconnect(record, app)


def _get_profile(app, client, query_string=None):
    """GET /profile and return (response, template_context)."""
    with captured_templates(app) as templates:
        response = client.get("/profile", query_string=query_string or {})
    assert response.status_code == 200, (
        f"Expected /profile to return 200, got {response.status_code}"
    )
    assert len(templates) == 1, (
        "Expected /profile to render exactly one template "
        f"(got {len(templates)}); route may not have reached render_template"
    )
    _, context = templates[0]
    return response, context


def _seed_baseline_expenses(app, user_id):
    """A small, spread-out expense history used as the 'all-time' baseline."""
    expenses = [
        (12.50, "Food", "2025-01-05"),
        (45.00, "Transport", "2025-03-10"),
        (89.99, "Bills", "2025-06-20"),
    ]
    for amount, category, expense_date in expenses:
        _insert_expense(app, user_id, amount, category, expense_date)
    return {
        "total_spent": sum(a for a, _, _ in expenses),
        "transaction_count": len(expenses),
        "categories": {c for _, c, _ in expenses},
        "top_category": "Bills",  # highest single amount
    }


def _seed_range_test_expenses(app, user_id):
    """Expenses split across, before, and after a Jan 2025 window."""
    in_range = [
        (10.00, "Food", "2025-01-05"),
        (20.00, "Transport", "2025-01-15"),
        (30.00, "Bills", "2025-01-25"),
    ]
    out_of_range = [
        (999.00, "Health", "2025-02-01"),  # after range
        (999.00, "Shopping", "2024-12-20"),  # before range
    ]
    for amount, category, expense_date in in_range + out_of_range:
        _insert_expense(app, user_id, amount, category, expense_date)
    return {
        "total_spent": sum(a for a, _, _ in in_range),
        "transaction_count": len(in_range),
        "categories": {c for _, c, _ in in_range},
        "excluded_categories": {c for _, c, _ in out_of_range},
        "top_category": "Bills",
    }


# --------------------------------------------------------------------- #
# No filter -> all-time view (regression)                                #
# --------------------------------------------------------------------- #

class TestNoFilterRegression:
    def test_no_filter_returns_alltime_stats_transactions_categories(self, app, auth_client):
        baseline = _seed_baseline_expenses(app, auth_client.user_id)

        response, context = _get_profile(app, auth_client)

        stats = context["stats"]
        assert stats["total_spent"] == pytest.approx(baseline["total_spent"]), (
            "Unfiltered view should total every expense the user has"
        )
        assert stats["transaction_count"] == baseline["transaction_count"], (
            "Unfiltered view should count every expense the user has"
        )
        assert stats["top_category"] == baseline["top_category"]

        transaction_dates = {row["date"] for row in context["transactions"]}
        assert transaction_dates == {"2025-01-05", "2025-03-10", "2025-06-20"}, (
            "Unfiltered transaction list should include every expense, not a subset"
        )

        category_names = {c["name"] for c in context["categories"]}
        assert category_names == baseline["categories"], (
            "Unfiltered category breakdown should cover every category the user spent in"
        )

        assert not context.get("start_date"), "No filter was applied; start_date should be empty"
        assert not context.get("end_date"), "No filter was applied; end_date should be empty"


# --------------------------------------------------------------------- #
# Valid start_date + end_date range                                      #
# --------------------------------------------------------------------- #

class TestValidDateRange:
    def test_valid_range_scopes_summary_stats(self, app, auth_client):
        expected = _seed_range_test_expenses(app, auth_client.user_id)

        _, context = _get_profile(
            app, auth_client, {"start_date": "2025-01-01", "end_date": "2025-01-31"}
        )

        stats = context["stats"]
        assert stats["total_spent"] == pytest.approx(expected["total_spent"]), (
            "Filtered total should only sum expenses inside the requested range"
        )
        assert stats["transaction_count"] == expected["transaction_count"], (
            "Filtered count should exclude expenses outside the requested range"
        )
        assert stats["top_category"] == expected["top_category"]

    def test_valid_range_scopes_transaction_list(self, app, auth_client):
        expected = _seed_range_test_expenses(app, auth_client.user_id)

        _, context = _get_profile(
            app, auth_client, {"start_date": "2025-01-01", "end_date": "2025-01-31"}
        )

        transactions = context["transactions"]
        assert len(transactions) == expected["transaction_count"], (
            "Transaction list length should match the number of in-range expenses"
        )
        dates = {row["date"] for row in transactions}
        assert dates == {"2025-01-05", "2025-01-15", "2025-01-25"}, (
            "Only expenses dated within the inclusive range should appear"
        )
        assert all(
            row["date"] >= "2025-01-01" and row["date"] <= "2025-01-31"
            for row in transactions
        ), "No out-of-range transaction should leak into the filtered list"

    def test_valid_range_scopes_category_breakdown(self, app, auth_client):
        expected = _seed_range_test_expenses(app, auth_client.user_id)

        _, context = _get_profile(
            app, auth_client, {"start_date": "2025-01-01", "end_date": "2025-01-31"}
        )

        categories = context["categories"]
        category_names = {c["name"] for c in categories}
        assert category_names == expected["categories"], (
            "Category breakdown should only include categories with in-range spend"
        )
        assert category_names.isdisjoint(expected["excluded_categories"]), (
            "Category breakdown must not include out-of-range categories "
            "(Health, Shopping)"
        )

        by_name = {c["name"]: c for c in categories}
        assert by_name["Food"]["amount"] == pytest.approx(10.00)
        assert by_name["Transport"]["amount"] == pytest.approx(20.00)
        assert by_name["Bills"]["amount"] == pytest.approx(30.00)

        # Percentages should be of the *filtered* total (60.00), not the
        # all-time total (which would include the two 999.00 outliers).
        assert by_name["Food"]["percent"] == pytest.approx(17, abs=1)
        assert by_name["Transport"]["percent"] == pytest.approx(33, abs=1)
        assert by_name["Bills"]["percent"] == pytest.approx(50, abs=1)


# --------------------------------------------------------------------- #
# Open-ended ranges (only one of start_date / end_date supplied)         #
# --------------------------------------------------------------------- #

class TestOpenEndedRange:
    def test_only_start_date_includes_everything_on_or_after_it(self, app, auth_client):
        user_id = auth_client.user_id
        _insert_expense(app, user_id, 5.00, "Food", "2025-01-01")  # before start, excluded
        _insert_expense(app, user_id, 15.00, "Transport", "2025-01-15")  # after start
        _insert_expense(app, user_id, 25.00, "Bills", "2025-02-01")  # after start

        _, context = _get_profile(app, auth_client, {"start_date": "2025-01-10"})

        stats = context["stats"]
        assert stats["total_spent"] == pytest.approx(40.00), (
            "start_date-only filter should include everything from that date onward"
        )
        assert stats["transaction_count"] == 2
        dates = {row["date"] for row in context["transactions"]}
        assert dates == {"2025-01-15", "2025-02-01"}
        assert "2025-01-01" not in dates, (
            "Expense before start_date must be excluded from an open-ended forward range"
        )
        category_names = {c["name"] for c in context["categories"]}
        assert category_names == {"Transport", "Bills"}

    def test_only_end_date_includes_everything_on_or_before_it(self, app, auth_client):
        user_id = auth_client.user_id
        _insert_expense(app, user_id, 5.00, "Food", "2025-01-01")  # before end
        _insert_expense(app, user_id, 15.00, "Transport", "2025-01-15")  # equals end (inclusive)
        _insert_expense(app, user_id, 25.00, "Bills", "2025-02-01")  # after end, excluded

        _, context = _get_profile(app, auth_client, {"end_date": "2025-01-15"})

        stats = context["stats"]
        assert stats["total_spent"] == pytest.approx(20.00), (
            "end_date-only filter should include everything up to and including that date"
        )
        assert stats["transaction_count"] == 2
        dates = {row["date"] for row in context["transactions"]}
        assert dates == {"2025-01-01", "2025-01-15"}
        assert "2025-02-01" not in dates, (
            "Expense after end_date must be excluded from an open-ended backward range"
        )
        category_names = {c["name"] for c in context["categories"]}
        assert category_names == {"Food", "Transport"}


# --------------------------------------------------------------------- #
# Malformed / reversed ranges -> fall back to all-time view              #
# --------------------------------------------------------------------- #

class TestMalformedDateFallback:
    @pytest.mark.parametrize(
        "query_string",
        [
            {"start_date": "not-a-date"},
            {"end_date": "31-01-2025"},
            {"start_date": "2025-13-40", "end_date": "2025-01-31"},
            {"start_date": "2025-01-15", "end_date": "banana"},
        ],
        ids=["bad-start", "wrong-format-end", "invalid-calendar-date", "bad-end"],
    )
    def test_malformed_date_falls_back_to_alltime_view(self, app, auth_client, query_string):
        baseline = _seed_baseline_expenses(app, auth_client.user_id)

        response, context = _get_profile(app, auth_client, query_string)

        assert response.status_code == 200, (
            "A malformed date must not crash the page"
        )
        stats = context["stats"]
        assert stats["total_spent"] == pytest.approx(baseline["total_spent"]), (
            "Malformed date input should fall back to the unfiltered all-time total"
        )
        assert stats["transaction_count"] == baseline["transaction_count"]
        category_names = {c["name"] for c in context["categories"]}
        assert category_names == baseline["categories"]


class TestReversedRangeFallback:
    def test_start_after_end_falls_back_to_alltime_view(self, app, auth_client):
        baseline = _seed_baseline_expenses(app, auth_client.user_id)

        response, context = _get_profile(
            app, auth_client, {"start_date": "2025-06-01", "end_date": "2025-01-01"}
        )

        assert response.status_code == 200, (
            "start_date after end_date must not crash the page"
        )
        stats = context["stats"]
        assert stats["total_spent"] == pytest.approx(baseline["total_spent"]), (
            "A reversed range should fall back to the unfiltered all-time total, "
            "not be silently swapped or produce a partial result"
        )
        assert stats["transaction_count"] == baseline["transaction_count"]
        category_names = {c["name"] for c in context["categories"]}
        assert category_names == baseline["categories"]


# --------------------------------------------------------------------- #
# Zero matches in the filtered range                                     #
# --------------------------------------------------------------------- #

class TestZeroMatchState:
    def test_zero_matches_returns_empty_state_without_crash(self, app, auth_client):
        _seed_baseline_expenses(app, auth_client.user_id)  # all in 2025

        response, context = _get_profile(
            app, auth_client, {"start_date": "2030-01-01", "end_date": "2030-12-31"}
        )

        assert response.status_code == 200, (
            "A range with zero matching expenses must not crash the page "
            "(e.g. via division by zero in category percentages)"
        )
        stats = context["stats"]
        assert stats["total_spent"] == 0, "Zero matches should total to zero, not raise"
        assert stats["transaction_count"] == 0
        assert context["transactions"] == [], "No transactions should be listed"
        assert context["categories"] == [], (
            "Category breakdown must be empty (and computed without a ZeroDivisionError) "
            "when nothing matches the range"
        )


# --------------------------------------------------------------------- #
# Auth guard                                                             #
# --------------------------------------------------------------------- #

class TestAuthGuard:
    def test_unauthenticated_no_filter_redirects_to_login(self, app, client):
        with app.test_request_context():
            expected_login_url = url_for("login")

        response = client.get("/profile")

        assert response.status_code == 302, (
            "Unauthenticated access to /profile must redirect, not render"
        )
        assert response.headers["Location"] == expected_login_url, (
            "Unauthenticated /profile should redirect to the login page"
        )

    @pytest.mark.parametrize(
        "query_string",
        [
            {"start_date": "2025-01-01", "end_date": "2025-01-31"},
            {"start_date": "not-a-date"},
            {"start_date": "2025-06-01", "end_date": "2025-01-01"},
        ],
        ids=["valid-range", "malformed", "reversed-range"],
    )
    def test_unauthenticated_with_filter_redirects_to_login(self, app, client, query_string):
        with app.test_request_context():
            expected_login_url = url_for("login")

        response = client.get("/profile", query_string=query_string)

        assert response.status_code == 302, (
            "The auth guard must apply regardless of any filter query params supplied"
        )
        assert response.headers["Location"] == expected_login_url


# --------------------------------------------------------------------- #
# The date filter never widens scope beyond the logged-in user           #
# --------------------------------------------------------------------- #

class TestUserIsolation:
    def test_valid_range_never_includes_another_users_expenses(self, app, auth_client):
        owner_id = auth_client.user_id
        other_id = _create_other_user(app, email="other@example.com")

        # Same date, different users, deliberately overlapping the filter window.
        _insert_expense(app, owner_id, 10.00, "Food", "2025-01-10")
        _insert_expense(app, other_id, 999.00, "Bills", "2025-01-10")

        _, context = _get_profile(
            app, auth_client, {"start_date": "2025-01-01", "end_date": "2025-01-31"}
        )

        stats = context["stats"]
        assert stats["total_spent"] == pytest.approx(10.00), (
            "The other user's expense must not be included in the owner's filtered total"
        )
        assert stats["transaction_count"] == 1

        category_names = {c["name"] for c in context["categories"]}
        assert category_names == {"Food"}, (
            "The other user's category (Bills) must not leak into the breakdown"
        )
        assert all(
            row["amount"] != pytest.approx(999.00) for row in context["transactions"]
        ), "The other user's transaction must not appear in the owner's transaction list"

    def test_no_filter_never_includes_another_users_expenses(self, app, auth_client):
        owner_id = auth_client.user_id
        other_id = _create_other_user(app, email="other2@example.com")

        _insert_expense(app, owner_id, 10.00, "Food", "2025-01-10")
        _insert_expense(app, other_id, 999.00, "Bills", "2025-01-10")

        _, context = _get_profile(app, auth_client)

        stats = context["stats"]
        assert stats["total_spent"] == pytest.approx(10.00), (
            "Even the unfiltered all-time view must stay scoped to the session user"
        )
        assert stats["transaction_count"] == 1

    def test_user_id_query_param_is_ignored_scope_stays_on_session_user(self, app, auth_client):
        owner_id = auth_client.user_id
        other_id = _create_other_user(app, email="other3@example.com")

        _insert_expense(app, owner_id, 10.00, "Food", "2025-01-10")
        _insert_expense(app, other_id, 999.00, "Bills", "2025-01-10")

        # Attempt to widen scope via an unsupported query param.
        _, context = _get_profile(
            app,
            auth_client,
            {
                "start_date": "2025-01-01",
                "end_date": "2025-01-31",
                "user_id": str(other_id),
            },
        )

        stats = context["stats"]
        assert stats["total_spent"] == pytest.approx(10.00), (
            "There is no supported way to widen the query scope via query params; "
            "scope must remain tied to session['user_id']"
        )
        assert stats["transaction_count"] == 1
