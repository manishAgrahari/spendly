# Spec: Registration

## Overview
Implement user registration for Spendly by wiring up the existing `/register` route to actually create accounts. This is Step 2 of the roadmap, building directly on the data layer from Step 1, and is the prerequisite for login, profile, and every authenticated expense-tracking feature that follows. The route and template already exist as placeholders; this step makes account creation actually work end to end.

## Depends on
- Step 1 — Database Setup (`database/db.py`: `get_db()`, `init_db()`, `users` table). Already complete and verified in `database/db.py`.

## Routes
- `GET /register` — renders the registration form — public (already implemented, unchanged)
- `POST /register` — creates a new user account, hashes the password, handles duplicate emails, starts a session, and redirects — public

## Database changes
No database changes. The `users` table already has every column this feature needs (`id`, `name`, `email`, `password_hash`, `created_at`) — verified against the current `database/db.py`.

## Templates
- **Create:** none
- **Modify:** `templates/register.html` — no structural changes; it already supports `{% if error %}{{ error }}{% endif %}`, so the route just needs to populate `error` and re-render on failure instead of redirecting

## Files to change
- `app.py`
  - Add a `secret_key` to the Flask app config (required for sessions) if not already set
  - Add POST handling to `/register`: read `name`/`email`/`password` from the form, validate presence, hash the password with werkzeug, insert the user via a parameterized query, catch `sqlite3.IntegrityError` for duplicate email
  - On success: store `user_id` in the session and redirect to `/`
  - On failure: re-render `register.html` with an `error` message and a 200/400 response (no redirect, no crash)
- `database/db.py` — no changes expected

## Files to create
- None

## New dependencies
No new dependencies.

## Rules for implementation
- No SQLAlchemy or ORMs
- Parameterised queries only — no string formatting in SQL
- Passwords hashed with werkzeug (`generate_password_hash`)
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- Duplicate email and validation errors must re-render the form with `error` set — never redirect on failure
- Never store or log plaintext passwords

## Definition of done
- [ ] `GET /register` still renders the form unchanged
- [ ] Submitting a valid name/email/password creates a row in `users` with a hashed password (not plaintext) — verifiable via `sqlite3` on `expense_tracker.db`
- [ ] Submitting a duplicate email shows an error on the same page instead of a 500 or a second inserted row
- [ ] Submitting with missing/invalid fields shows an error instead of crashing
- [ ] After successful registration, the session contains the new user and the browser is redirected away from `/register`
- [ ] No SQL in the new code is built via string formatting or concatenation
