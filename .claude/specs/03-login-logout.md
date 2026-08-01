# Spec: Login and Logout

## Overview
Implement authentication for Spendly: `POST /login` verifies a user's email and password against the `users` table and starts a session, and `/logout` clears that session. This is Step 3 of the roadmap, directly following Registration (Step 2), and is the second half of the auth flow — every account created via `/register` needs a way back in, and a way to sign out. It also unblocks Step 4 (Profile), which needs a logged-in session to know whose data to show.

## Depends on
- Step 1 — Database Setup (`database/db.py`: `get_db()`, `users` table). Complete.
- Step 2 — Registration (`app.py`: `SECRET_KEY` configured, `session["user_id"]` established as the session convention, password hashing with werkzeug). Complete — this step reuses the same session key and hashing scheme.

## Routes
- `GET /login` — renders the login form — public (already implemented, unchanged)
- `POST /login` — verifies email/password, starts a session, redirects — public
- `GET /logout` — clears the session, redirects to landing — logged-in (safe to hit while logged out too; just becomes a no-op redirect)

## Database changes
No database changes. The `users` table already has `email` and `password_hash`, which is everything login needs. Verified against the current `database/db.py`.

## Templates
- **Create:** none
- **Modify:**
  - `templates/login.html` — no structural changes; it already supports `{% if error %}{{ error }}{% endif %}`, so the route just needs to populate `error` and re-render on failure instead of redirecting
  - `templates/base.html` — the nav currently always shows "Sign in" / "Get started" regardless of auth state, and there is no link to `/logout` anywhere. Make the nav conditional on `session.user_id`: show "Sign in" + "Get started" when logged out (current behavior, unchanged), show a "Logout" link when logged in. `session` is available in Jinja by default, no extra plumbing needed.

## Files to change
- `app.py`
  - Add `POST` handling to `/login`: read `email`/`password` from the form, look up the user by email, verify the password with `werkzeug.security.check_password_hash`, store `session["user_id"]` on success and redirect to `/`
  - On any failure (no matching email, wrong password), re-render `login.html` with **one generic error message** — do not reveal whether the email exists (avoids account enumeration)
  - Replace the `/logout` placeholder: clear the session (`session.pop("user_id", None)` or `session.clear()`) and redirect to `/`
- `templates/base.html` — wrap the nav links in `{% if session.user_id %}...{% else %}...{% endif %}`

## Files to create
- None

## New dependencies
No new dependencies. Uses `werkzeug.security.check_password_hash`, already available (same package as `generate_password_hash` used in Registration).

## Rules for implementation
- No SQLAlchemy or ORMs
- Parameterised queries only — no string formatting in SQL
- Passwords hashed with werkzeug — login must use `check_password_hash` against the stored hash, never compare plaintext
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- Use one generic error message ("Invalid email or password.") for both "email not found" and "wrong password" — never disclose which one failed
- Never store or log plaintext passwords
- Reuse the existing `session["user_id"]` convention from Registration — do not introduce a different session key

## Definition of done
- [ ] `GET /login` still renders the form unchanged
- [ ] Logging in with a valid, previously-registered email/password redirects away from `/login` and the session is set (visible as a `session` cookie)
- [ ] Logging in with a non-existent email shows the generic error, not a 500
- [ ] Logging in with a correct email but wrong password shows the same generic error (verify both cases render identical text)
- [ ] Visiting `/logout` while logged in clears the session and redirects to `/`
- [ ] After logout, the nav shows "Sign in" / "Get started" again instead of "Logout"
- [ ] While logged in, the nav shows "Logout" instead of "Sign in" / "Get started"
- [ ] No SQL in the new code is built via string formatting or concatenation
