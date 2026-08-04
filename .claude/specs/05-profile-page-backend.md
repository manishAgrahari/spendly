# Spec: Profile Page Backend

## Overview
Step 4 built the `/profile` page's full visual layout using hardcoded Python dicts/lists in `app.py`, deliberately deferring real data. This step replaces that hardcoded data with real, database-backed queries scoped to the logged-in user — so the profile page shows the actual signed-in user's account details and their real expense history and category totals, sourced from the `users` and `expenses` tables via `get_db()`.

## Depends on
- Step 1: Database setup (`users` and `expenses` tables must exist)
- Step 2: Registration (user accounts must be creatable)
- Step 3: Login + Logout (session must be set; `/profile` must be a protected route)
- Step 4: Profile page design (template `profile.html` and its four sections already exist and expect `user`, `stats`, `transactions`, `categories` context variables)

## Routes
No new routes. Modifies the existing route:
- `GET /profile` — render the profile page with real data for the logged-in user — logged-in only (redirect to `/login` if not authenticated, unchanged from Step 4)

## Database changes
No database changes. The existing `users` and `expenses` tables (see `database/db.py`) are sufficient — this step only adds `SELECT` queries against them.

## Templates
- **Modify:** `templates/profile.html` — no structural changes expected; it already consumes `user`, `stats`, `transactions`, `categories` via Jinja. If any hardcoded assumption from Step 4 doesn't hold for real data (e.g. an empty-state case), adjust the template minimally to handle it.
- **Create:** none

## Files to change
- `app.py` — rewrite the `/profile` view (currently hardcoded, see the existing `profile()` function) to build its context from real queries instead of literal data:
  - `user`: look up the logged-in user's `name`, `email`, `created_at` from the `users` table via `session["user_id"]`; compute `initials` and a human-readable `member_since` (e.g. "March 2026") in Python from the row
  - `stats`: compute `total_spent` (`SUM(amount)`), `transaction_count` (`COUNT(*)`), and `top_category` (category with the highest summed amount) via SQL aggregate queries filtered by `user_id`
  - `transactions`: real rows from `expenses` for this user, ordered by `date` descending, capped at a reasonable limit (e.g. 10)
  - `categories`: per-category `SUM(amount)` for this user, with `percent` computed in Python relative to `total_spent`

## Files to create
None.

## New dependencies
No new dependencies.

## Rules for implementation
- No SQLAlchemy or ORMs — raw `sqlite3` via `get_db()` only
- Parameterised queries only — never string-format SQL, especially since queries are filtered by `session["user_id"]`
- Passwords hashed with werkzeug (unchanged, no auth logic touched in this step)
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- No inline styles
- Authentication guard unchanged: check `session.get("user_id")`; if absent, `redirect(url_for("login"))`
- Always scope every query by the logged-in `user_id` from the session — never trust client input to determine whose data is shown
- Guard against division by zero when computing category percentages for a user with `total_spent == 0`
- No new reusable abstractions (e.g. no ORM-style models, no `login_required` decorator) — keep it a single inline view function, consistent with Step 4's style

## Definition of done
- [ ] Visiting `/profile` without being logged in redirects to `/login`
- [ ] Visiting `/profile` while logged in returns HTTP 200
- [ ] The user info card shows the actual logged-in user's real name and email (not the Step 4 placeholder "Demo User" text unless that genuinely is the logged-in user)
- [ ] Total spent, transaction count, and top category are computed from real `SUM`/`COUNT` queries on the `expenses` table, not hardcoded
- [ ] The transaction history table shows the logged-in user's real expenses — adding a new expense via the `seed-expense` skill and reloading `/profile` shows it appear
- [ ] The category breakdown reflects real per-category totals and percentages for that user
- [ ] A user with zero expenses sees an empty/zero state on `/profile` without any error (no division-by-zero crash)
- [ ] No hex colour values appear in `profile.html` — only CSS variables
