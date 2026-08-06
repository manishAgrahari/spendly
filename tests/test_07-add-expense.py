"""
Tests for the "Add Expense" feature.

Spec: .claude/specs/07-add-expense.md

`GET /expenses/add` and `POST /expenses/add` are both protected routes
(logged-in only) handled by the same `add_expense()` view, matching the
`GET`/`POST` pattern already used by `register()`/`login()`.

- `GET` renders a form with fields for amount, category (a dropdown
  populated from `database.db.CATEGORIES` — the single source of truth),
  date (`type="date"`, defaulting to today), and an optional description.
- `POST` validates `amount` (present, numeric, `> 0`), `category` (must be
  one of `CATEGORIES`), and `date` (must parse as `%Y-%m-%d`). On any
  validation failure the form is re-rendered with an error and nothing is
  inserted. On success, a new row is inserted into `expenses` scoped to
  `session["user_id"]` (never a `user_id` supplied by the form) and the
  response redirects to `/profile`. `description` is optional.
- Per the spec's Definition of Done, a newly added expense must
  immediately be reflected in `/profile`'s total spent, transaction count,
  and category breakdown — no server restart required.

These tests exercise the route purely through the Flask test client and
verify behaviour via:
  - HTTP status codes / redirect targets
  - direct DB reads (via `get_db()`) to confirm insert / no-insert side
    effects
  - the actual `stats` / `transactions` / `categories` context passed to
    `profile.html` (captured via Flask's `template_rendered` signal, per
    the pattern already established by `tests/test_date_filter_profile_page.py`
    for step 6) to confirm the newly added expense is reflected there
  - light, black-box HTML landmark checks on the rendered add-expense form
    (field names, category options, date input type) rather than assuming
    any particular template-context variable names for that new template

Because `database.db.get_db()` connects to a module-level `DB_PATH`
constant (not a Flask config key), isolation is achieved by monkeypatching
`database.db.DB_PATH` to a per-test temp file before `init_db()` runs —
this test file never touches the real `expense_tracker.db` and shares no
state with any other test file.
"""

import re
from contextlib import contextmanager
from datetime import date

import pytest
from flask import template_rendered, url_for
from werkzeug.security import generate_password_hash

import database.db as db_module
from app import app as flask_app
from database.db import CATEGORIES, get_db, init_db

DEFAULT_PASSWORD = "password123"
TODAY = date.today().strftime("%Y-%m-%d")


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
    client for convenience when asserting DB side effects.
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


def _all_expenses(app):
    """Every row in `expenses`, across all users — used to assert 'no insert happened'."""
    with app.app_context():
        conn = get_db()
        rows = conn.execute("SELECT * FROM expenses").fetchall()
        conn.close()
        return [dict(row) for row in rows]


def _expenses_for_user(app, user_id):
    with app.app_context():
        conn = get_db()
        rows = conn.execute(
            "SELECT * FROM expenses WHERE user_id = ?", (user_id,)
        ).fetchall()
        conn.close()
        return [dict(row) for row in rows]


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


def _get_add_expense_page(app, client):
    """GET /expenses/add and return (response, [(template, context), ...])."""
    with captured_templates(app) as templates:
        response = client.get("/expenses/add")
    return response, templates


def _post_add_expense(app, client, **overrides):
    """POST /expenses/add with sane valid defaults, overridable per-field.

    Pass a field as `None` to omit it from the submitted form data entirely
    (simulating a field that was never sent), rather than sending it as an
    empty string.
    """
    data = {
        "amount": "25.00",
        "category": "Food",
        "date": TODAY,
        "description": "Groceries",
    }
    data.update(overrides)
    data = {k: v for k, v in data.items() if v is not None}

    with captured_templates(app) as templates:
        response = client.post("/expenses/add", data=data)
    return response, templates


def _get_profile_context(app, client):
    with captured_templates(app) as templates:
        response = client.get("/profile")
    assert response.status_code == 200, (
        f"Expected /profile to return 200, got {response.status_code}"
    )
    assert len(templates) == 1, (
        "Expected /profile to render exactly one template"
    )
    _, context = templates[0]
    return response, context


# --------------------------------------------------------------------- #
# Auth guard — GET and POST both protected                              #
# --------------------------------------------------------------------- #

class TestAuthGuard:
    def test_get_unauthenticated_redirects_to_login(self, app, client):
        with app.test_request_context():
            expected_login_url = url_for("login")

        response = client.get("/expenses/add")

        assert response.status_code == 302, (
            "Unauthenticated GET /expenses/add must redirect, not render the form"
        )
        assert response.headers["Location"] == expected_login_url, (
            "Unauthenticated GET /expenses/add should redirect to the login page"
        )

    def test_post_unauthenticated_redirects_to_login(self, app, client):
        with app.test_request_context():
            expected_login_url = url_for("login")

        response = client.post(
            "/expenses/add",
            data={"amount": "10.00", "category": "Food", "date": TODAY, "description": ""},
        )

        assert response.status_code == 302, (
            "Unauthenticated POST /expenses/add must redirect, not process the submission"
        )
        assert response.headers["Location"] == expected_login_url

    def test_post_unauthenticated_does_not_insert_a_row(self, app, client):
        client.post(
            "/expenses/add",
            data={"amount": "10.00", "category": "Food", "date": TODAY, "description": ""},
        )

        assert _all_expenses(app) == [], (
            "An unauthenticated POST must never insert an expense into the DB, "
            "regardless of how the request is otherwise formed"
        )


# --------------------------------------------------------------------- #
# GET /expenses/add — form rendering while logged in                    #
# --------------------------------------------------------------------- #

class TestGetForm:
    def test_get_authenticated_returns_200(self, app, auth_client):
        response, _ = _get_add_expense_page(app, auth_client)
        assert response.status_code == 200, (
            "A logged-in GET /expenses/add should render the form, not redirect or error"
        )

    def test_get_form_has_amount_category_date_description_fields(self, app, auth_client):
        response, _ = _get_add_expense_page(app, auth_client)
        html = response.data

        assert b'name="amount"' in html, "Form must have an amount field"
        assert b'name="category"' in html, "Form must have a category field"
        assert b'name="date"' in html, "Form must have a date field"
        assert b'name="description"' in html, "Form must have a description field"

    def test_get_form_date_field_is_html5_date_input(self, app, auth_client):
        response, _ = _get_add_expense_page(app, auth_client)
        assert b'type="date"' in response.data, (
            "The date field should be an HTML5 date input, per the spec"
        )

    def test_get_form_date_defaults_to_today(self, app, auth_client):
        response, _ = _get_add_expense_page(app, auth_client)
        assert TODAY.encode() in response.data, (
            f"The date field should default to today ({TODAY}) when the form is first shown"
        )

    def test_get_form_category_dropdown_populated_from_categories(self, app, auth_client):
        response, _ = _get_add_expense_page(app, auth_client)
        html = response.data.decode()

        for category in CATEGORIES:
            assert category in html, (
                f"Category dropdown should include {category!r}, sourced from "
                "database.db.CATEGORIES (the single source of truth)"
            )

    def test_get_form_page_has_no_hardcoded_hex_colors(self, app, auth_client):
        response, _ = _get_add_expense_page(app, auth_client)
        html = response.data.decode()

        inline_style_hex = re.findall(r'style="[^"]*#[0-9a-fA-F]{3,6}', html)
        assert inline_style_hex == [], (
            "The add-expense template must use CSS variables, not hardcoded hex "
            f"colour values, in inline styles; found: {inline_style_hex}"
        )


# --------------------------------------------------------------------- #
# POST /expenses/add — happy path                                       #
# --------------------------------------------------------------------- #

class TestHappyPath:
    def test_valid_submission_redirects_to_profile(self, app, auth_client):
        with app.test_request_context():
            expected_profile_url = url_for("profile")

        response, _ = _post_add_expense(app, auth_client)

        assert response.status_code == 302, (
            "A valid submission should redirect (not re-render the form)"
        )
        assert response.headers["Location"] == expected_profile_url, (
            "A valid submission should redirect to /profile"
        )

    def test_valid_submission_inserts_row_scoped_to_logged_in_user(self, app, auth_client):
        _post_add_expense(
            app, auth_client, amount="42.50", category="Bills", date=TODAY,
            description="Electric bill",
        )

        rows = _expenses_for_user(app, auth_client.user_id)
        assert len(rows) == 1, "Exactly one expense should be inserted for the logged-in user"

        row = rows[0]
        assert row["user_id"] == auth_client.user_id, (
            "The inserted expense must be scoped to the logged-in user's id"
        )
        assert row["amount"] == pytest.approx(42.50)
        assert row["category"] == "Bills"
        assert row["date"] == TODAY
        assert row["description"] == "Electric bill"

    def test_valid_submission_never_trusts_user_id_from_form(self, app, auth_client):
        other_id = _create_other_user(app, email="attacker@example.com")

        # Attempt to spoof ownership via an unsupported/extra form field.
        _post_add_expense(
            app, auth_client, amount="99.00", category="Shopping", date=TODAY,
            description="Spoof attempt", user_id=str(other_id),
        )

        assert _expenses_for_user(app, other_id) == [], (
            "A user_id supplied in the form must never be trusted; "
            "the row must not be attributed to the other user"
        )
        owner_rows = _expenses_for_user(app, auth_client.user_id)
        assert len(owner_rows) == 1, (
            "The expense must instead be attributed to session['user_id']"
        )
        assert owner_rows[0]["user_id"] == auth_client.user_id

    def test_valid_submission_with_empty_description_succeeds(self, app, auth_client):
        response, _ = _post_add_expense(
            app, auth_client, amount="15.00", category="Food", date=TODAY, description="",
        )

        assert response.status_code == 302, (
            "description is optional — an empty description must still succeed"
        )
        rows = _expenses_for_user(app, auth_client.user_id)
        assert len(rows) == 1, "The row should still be inserted with an empty description"
        assert rows[0]["amount"] == pytest.approx(15.00)

    def test_valid_submission_with_omitted_description_succeeds(self, app, auth_client):
        response, _ = _post_add_expense(
            app, auth_client, amount="15.00", category="Food", date=TODAY, description=None,
        )

        assert response.status_code == 302, (
            "description is optional — omitting the field entirely must still succeed"
        )
        rows = _expenses_for_user(app, auth_client.user_id)
        assert len(rows) == 1, "The row should still be inserted when description is omitted"

    def test_valid_submission_with_long_description_succeeds(self, app, auth_client):
        long_description = "A" * 2000
        response, _ = _post_add_expense(
            app, auth_client, amount="15.00", category="Food", date=TODAY,
            description=long_description,
        )

        assert response.status_code == 302, (
            "The spec places no length restriction on description; a long value must succeed"
        )
        rows = _expenses_for_user(app, auth_client.user_id)
        assert len(rows) == 1
        assert rows[0]["description"] == long_description


# --------------------------------------------------------------------- #
# POST /expenses/add — amount validation                                #
# --------------------------------------------------------------------- #

class TestAmountValidation:
    @pytest.mark.parametrize(
        "amount_value",
        ["", "not-a-number", "abc", "12,50", "12.5.0", "$25.00"],
        ids=["empty", "alpha", "words", "comma-decimal", "double-dot", "currency-symbol"],
    )
    def test_missing_or_non_numeric_amount_rerenders_without_insert(
        self, app, auth_client, amount_value
    ):
        response, templates = _post_add_expense(app, auth_client, amount=amount_value)

        assert response.status_code == 200, (
            "An invalid amount should re-render the form (200), not redirect"
        )
        assert _all_expenses(app) == [], "No row should be inserted when amount is invalid"
        assert len(templates) == 1
        template, context = templates[0]
        assert "add.html" in template.name, "Should re-render the add-expense form template"
        assert context.get("error"), (
            "The re-rendered form should carry a truthy error message for the user"
        )

    @pytest.mark.parametrize(
        "amount_value",
        ["0", "0.0", "0.00", "-1", "-25.00", "-0.01"],
        ids=["zero-int", "zero-float", "zero-2dp", "neg-int", "neg-float", "neg-small"],
    )
    def test_zero_or_negative_amount_rerenders_without_insert(
        self, app, auth_client, amount_value
    ):
        response, templates = _post_add_expense(app, auth_client, amount=amount_value)

        assert response.status_code == 200, (
            "A zero or negative amount should re-render the form (200), not redirect"
        )
        assert _all_expenses(app) == [], (
            "No row should be inserted for a zero or negative amount"
        )
        template, context = templates[0]
        assert context.get("error"), "A zero/negative amount must produce an error message"


# --------------------------------------------------------------------- #
# POST /expenses/add — category validation                              #
# --------------------------------------------------------------------- #

class TestCategoryValidation:
    @pytest.mark.parametrize(
        "category_value",
        [
            "",
            "Groceries",
            "food",  # wrong case
            "Not A Category",
            "Food'; DROP TABLE expenses;--",  # SQL injection attempt
        ],
        ids=["empty", "unknown", "wrong-case", "made-up", "sql-injection"],
    )
    def test_invalid_category_rerenders_without_insert(self, app, auth_client, category_value):
        response, templates = _post_add_expense(app, auth_client, category=category_value)

        assert response.status_code == 200, (
            "A category outside CATEGORIES should re-render the form (200), not redirect"
        )
        assert _all_expenses(app) == [], (
            "No row should be inserted when category is not one of CATEGORIES"
        )
        template, context = templates[0]
        assert context.get("error"), "An invalid category must produce an error message"

        # The SQL-injection-shaped payload above must be handled safely as
        # ordinary invalid input (parameterised queries) rather than
        # crashing or corrupting the schema — proven by `_all_expenses(app)`
        # above still returning `[]` without raising.

    def test_valid_categories_are_all_accepted(self, app, auth_client):
        for category in CATEGORIES:
            response, _ = _post_add_expense(app, auth_client, category=category)
            assert response.status_code == 302, (
                f"{category!r} is in CATEGORIES and must be accepted as valid"
            )

        rows = _expenses_for_user(app, auth_client.user_id)
        assert len(rows) == len(CATEGORIES), (
            "Every category in CATEGORIES should have produced a successful insert"
        )
        assert {row["category"] for row in rows} == set(CATEGORIES)


# --------------------------------------------------------------------- #
# POST /expenses/add — date validation                                  #
# --------------------------------------------------------------------- #

class TestDateValidation:
    @pytest.mark.parametrize(
        "date_value",
        ["", "not-a-date", "31-01-2025", "2025/01/31", "2025-13-40", "2025-02-30"],
        ids=["empty", "words", "dd-mm-yyyy", "slashes", "bad-month", "bad-day"],
    )
    def test_malformed_date_rerenders_without_insert(self, app, auth_client, date_value):
        response, templates = _post_add_expense(app, auth_client, date=date_value)

        assert response.status_code == 200, (
            "A malformed date should re-render the form (200), not redirect"
        )
        assert _all_expenses(app) == [], (
            "No row should be inserted when the date fails to parse as %Y-%m-%d"
        )
        template, context = templates[0]
        assert context.get("error"), "A malformed date must produce an error message"

    def test_well_formed_date_is_accepted(self, app, auth_client):
        response, _ = _post_add_expense(app, auth_client, date="2024-02-29")  # leap day
        assert response.status_code == 302, "A valid, well-formed date must be accepted"

        rows = _expenses_for_user(app, auth_client.user_id)
        assert len(rows) == 1
        assert rows[0]["date"] == "2024-02-29"


# --------------------------------------------------------------------- #
# Definition of done — the new expense is immediately reflected in       #
# /profile's stats, transaction list, and category breakdown             #
# --------------------------------------------------------------------- #

class TestProfileReflection:
    def test_new_expense_reflected_in_profile_total_and_count(self, app, auth_client):
        _insert_expense(app, auth_client.user_id, 12.50, "Food", "2025-01-05")

        _post_add_expense(app, auth_client, amount="10.00", category="Transport", date=TODAY)

        _, context = _get_profile_context(app, auth_client)
        stats = context["stats"]
        assert stats["total_spent"] == pytest.approx(22.50), (
            "The newly added expense's amount must be included in the profile total, "
            "with no server restart"
        )
        assert stats["transaction_count"] == 2, (
            "The newly added expense must be counted in the profile's transaction count"
        )

    def test_new_expense_reflected_in_profile_transaction_list(self, app, auth_client):
        _post_add_expense(
            app, auth_client, amount="30.00", category="Entertainment", date=TODAY,
            description="Concert tickets",
        )

        _, context = _get_profile_context(app, auth_client)
        transactions = context["transactions"]

        matching = [
            row for row in transactions
            if row["category"] == "Entertainment" and row["amount"] == pytest.approx(30.00)
        ]
        assert matching, (
            "The newly added expense must appear in the profile's transaction list"
        )
        assert matching[0]["date"] == TODAY
        assert matching[0]["description"] == "Concert tickets"

    def test_new_expense_reflected_in_profile_category_breakdown(self, app, auth_client):
        _insert_expense(app, auth_client.user_id, 50.00, "Bills", "2025-01-05")

        _post_add_expense(app, auth_client, amount="50.00", category="Health", date=TODAY)

        _, context = _get_profile_context(app, auth_client)
        by_name = {c["name"]: c for c in context["categories"]}

        assert "Health" in by_name, (
            "The newly added expense's category must appear in the category breakdown"
        )
        assert by_name["Health"]["amount"] == pytest.approx(50.00)
        # Two categories at 50.00 each -> total 100.00 -> 50% each.
        assert by_name["Health"]["percent"] == pytest.approx(50, abs=1), (
            "Category percentages must be recomputed against the new total, "
            "including the freshly added expense"
        )

    def test_new_expense_does_not_leak_into_another_users_profile(self, app, auth_client):
        other_id = _create_other_user(app, email="bystander@example.com")
        _insert_expense(app, other_id, 999.00, "Shopping", "2025-01-01")

        _post_add_expense(app, auth_client, amount="10.00", category="Food", date=TODAY)

        _, context = _get_profile_context(app, auth_client)
        stats = context["stats"]
        assert stats["total_spent"] == pytest.approx(10.00), (
            "Adding an expense for the logged-in user must not surface another "
            "user's unrelated expenses in their profile view"
        )
        assert stats["transaction_count"] == 1
