# Spec: Date Filter for Profile Page

## Overview
Step 5 wired the `/profile` page to real data, but it always shows the user's entire expense history — every transaction, every stat, every category total. This step adds an optional date range filter to `/profile` so the logged-in user can narrow the summary stats, transaction list, and category breakdown down to a specific window of time (e.g. "this month," or any custom start/end date), while still defaulting to the full all-time view when no filter is applied.

## Depends on
- Step 1: Database setup (`users` and `expenses` tables must exist)
- Step 3: Login + Logout (session must be set; `/profile` must remain a protected route)
- Step 4: Profile page design (`profile.html` layout and its four sections)
- Step 5: Profile page backend (`/profile` already builds `user`, `stats`, `transactions`, `categories` from real queries via `get_db()` — this step adds filtering on top of those same queries)

## Routes
No new routes. Modifies the existing route:
- `GET /profile` — accepts optional `start_date` and `end_date` query string parameters (`YYYY-MM-DD`) and, when present and valid, scopes `stats`, `transactions`, and `categories` to expenses with `date` in that inclusive range — logged-in only (unchanged auth guard, redirect to `/login` if not authenticated)

## Database changes
No database changes. `expenses.date` (see `database/db.py`) is already stored as an ISO `YYYY-MM-DD` string, which sorts and compares correctly with `?` parameters in a `BETWEEN`/`>=`/`<=` SQL clause. No new tables, columns, or constraints needed.

## Templates
- **Modify:** `templates/profile.html` — add a small filter form (two `type="date"` inputs for start/end, a "Filter" submit button, and a "Clear" link back to plain `/profile`) above the "Recent Transactions" section. The form uses `method="GET"` so the range lives in the URL and is shareable/bookmarkable. When a filter is active, show the selected range back to the user (e.g. "Showing Jan 1 – Jan 31, 2026") and preserve the submitted `start_date`/`end_date` values in the inputs on reload.
- **Create:** none

## Files to change
- `app.py`:
  - `profile()` — read `start_date` and `end_date` from `request.args`, validate them (see Rules below), and pass the effective range down to the three helper functions; pass the (possibly empty) filter values back to the template so the form can redisplay them
  - `_get_recent_transactions(user_id, limit=10, start_date=None, end_date=None)` — add an optional date range to the existing `WHERE user_id = ?` clause
  - `_get_summary_stats(user_id, start_date=None, end_date=None)` — same date range added to both the totals query and the top-category query
  - `_get_category_breakdown(user_id, total_spent, start_date=None, end_date=None)` — same date range added to the grouped query
- `static/css/style.css` — add styling for the new filter form using existing CSS variables (`--border`, `--radius-sm`/`--radius-md`, `--paper-card`, `--ink-muted`, etc.), consistent with the existing card-based profile layout

## Files to create
None.

## New dependencies
No new dependencies.

## Rules for implementation
- No SQLAlchemy or ORMs — raw `sqlite3` via `get_db()` only
- Parameterised queries only — date range values go through `?` placeholders, never string-formatted into SQL
- Passwords hashed with werkzeug (unchanged, no auth logic touched in this step)
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- No inline styles
- Authentication guard unchanged: check `session.get("user_id")`; if absent, `redirect(url_for("login"))`
- Always scope every query by the logged-in `user_id` from the session — the date filter narrows further, it never replaces the user scope
- Validate `start_date`/`end_date` with `datetime.strptime(value, "%Y-%m-%d")`; if either is malformed, ignore both and fall back to the unfiltered (all-time) view rather than erroring
- If both dates are present and `start_date` is after `end_date`, ignore both and fall back to the unfiltered view (don't 500, don't silently swap them)
- Either date may be supplied alone (open-ended range: "everything from this date on" / "everything up to this date")
- Guard against division by zero in category percentages when the filtered range has zero matching expenses (same as the existing all-time case)
- No new reusable abstractions (e.g. no query-builder class, no `login_required` decorator) — keep the filtering logic as plain conditional SQL clauses in the existing helper functions, consistent with Step 5's style

## Definition of done
- [ ] Visiting `/profile` with no query params shows the same all-time data as before this step (no regression)
- [ ] Visiting `/profile?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD` with a valid range shows only expenses whose `date` falls within that inclusive range, across stats, transactions, and category breakdown consistently
- [ ] The filter form's inputs are pre-filled with the current `start_date`/`end_date` after submitting, so the active filter is visible
- [ ] A "Clear" control returns to `/profile` with no filter applied
- [ ] Supplying only `start_date` or only `end_date` produces a correct open-ended range
- [ ] Supplying a malformed date (e.g. `start_date=notadate`) does not crash the page — it falls back to the all-time view
- [ ] Supplying `start_date` after `end_date` does not crash the page — it falls back to the all-time view
- [ ] A user with zero expenses in the selected range sees an empty/zero state without a division-by-zero error
- [ ] Filtering only affects the logged-in user's own data — no way to view another user's expenses via query params
- [ ] No hex colour values appear in the new filter form markup — only CSS variables
