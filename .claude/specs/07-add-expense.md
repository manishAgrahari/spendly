# Spec: Add Expense

## Overview
Steps 1–6 built the ability to view an existing expense history (profile stats, transaction list, category breakdown, date filtering) but there is still no way for a user to actually record a new expense — `/expenses/add` is currently a placeholder that returns the literal string `"Add expense — coming in Step 7"`. This step replaces that placeholder with a real form-backed route so a logged-in user can add a new expense (amount, category, date, optional description) to their own account, which then immediately shows up in the profile page's stats, transactions, and category breakdown.

## Depends on
- Step 1: Database setup (`expenses` table with `user_id`, `amount`, `category`, `date`, `description` columns must exist)
- Step 3: Login + Logout (session must be set; `/expenses/add` must become a protected route)
- Step 4/5: Profile page design + backend (the page that will display the newly added expense)

## Routes
- `GET /expenses/add` — render the add-expense form — logged-in only
- `POST /expenses/add` — validate and insert a new expense for the logged-in user, then redirect to `/profile` — logged-in only

Both methods are handled by the existing `add_expense()` view (replacing its placeholder body), matching the `GET`/`POST` pattern already used by `register()` and `login()`.

## Database changes
No database changes. The `expenses` table (see `database/db.py`) already has every column this form needs: `user_id`, `amount`, `category`, `date`, `description` (nullable), plus `id` and `created_at` defaults. The existing `CATEGORIES` list in `database/db.py` (`Food`, `Transport`, `Bills`, `Health`, `Entertainment`, `Shopping`, `Other`) is the source of truth for the category dropdown — do not hardcode a separate category list in `app.py` or the template.

## Templates
- **Create:** `templates/expenses/add.html` — new form page with fields for amount, category (select, populated from `CATEGORIES`), date (`type="date"`, defaulting to today), and description (optional). Extends `base.html`, follows the same card/form visual style as `register.html`/`login.html`. Shows a validation error message in the same style as `register.html`'s `{{ error }}` block when present.
- **Modify:** none required, though `templates/profile.html` already links or could link to `/expenses/add` — verify at implementation time whether an "Add Expense" call-to-action needs wiring in from the profile page.

## Files to change
- `app.py`:
  - `add_expense()` — replace the placeholder string with a real `GET`/`POST` view:
    - Add `methods=["GET", "POST"]` to the `@app.route("/expenses/add")` decorator
    - Add the auth guard: `if not session.get("user_id"): return redirect(url_for("login"))`
    - On `GET`, render `templates/expenses/add.html`, passing `CATEGORIES` and a default date of today
    - On `POST`, read `amount`, `category`, `date`, `description` from `request.form`, validate them (see Rules below), and either re-render the form with an `error` message or `INSERT` the row scoped to `session["user_id"]` and redirect to `url_for("profile")`
  - Import `CATEGORIES` from `database.db` alongside the existing `get_db`, `init_db`, `seed_db` import

## Files to create
- `templates/expenses/add.html`

## New dependencies
No new dependencies.

## Rules for implementation
- No SQLAlchemy or ORMs — raw `sqlite3` via `get_db()` only
- Parameterised queries only — all form values go through `?` placeholders, never string-formatted into SQL
- Passwords hashed with werkzeug (unchanged, no auth logic touched in this step)
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- No inline styles
- Authentication guard: check `session.get("user_id")`; if absent, `redirect(url_for("login"))` — applies to both `GET` and `POST`
- Always insert with `user_id = session["user_id"]` — never trust a `user_id` from the form
- Validate `amount` is present and parses as a positive number (`float(amount) > 0`); on failure, re-render the form with an error and no insert
- Validate `category` is one of `database.db.CATEGORIES`; on failure, re-render the form with an error and no insert
- Validate `date` with `datetime.strptime(value, "%Y-%m-%d")`; on failure, re-render the form with an error and no insert
- `description` is optional — store `None`/empty rather than requiring it
- No new reusable abstractions (e.g. no generic form-validation helper, no `login_required` decorator) — keep validation as plain conditional checks in the view, consistent with `register()`'s style

## Definition of done
- [ ] Visiting `/expenses/add` while logged out redirects to `/login`
- [ ] Visiting `/expenses/add` while logged in shows a form with amount, category (dropdown from `CATEGORIES`), date (defaulted to today), and description fields
- [ ] Submitting the form with valid data inserts a new row into `expenses` scoped to the logged-in user's `id` and redirects to `/profile`
- [ ] The newly added expense immediately appears in `/profile`'s transaction list, total spent, and category breakdown without a server restart
- [ ] Submitting with a missing or non-numeric amount re-shows the form with an error and does not insert a row
- [ ] Submitting with a negative or zero amount re-shows the form with an error and does not insert a row
- [ ] Submitting with a category not in `CATEGORIES` re-shows the form with an error and does not insert a row
- [ ] Submitting with a malformed date re-shows the form with an error and does not insert a row
- [ ] Submitting with an empty description still succeeds (description is optional)
- [ ] No hex colour values appear in the new template markup — only CSS variables
