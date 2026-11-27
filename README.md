# MatchaTrail

MatchaTrail is a Django web app for Cebu matcha lovers. Explorers log the cafés they visit and the drinks they try, and Café Owners see the check-ins left at their cafés. It uses Django templates, Django authentication, and PostgreSQL (Supabase).

**Standard features:** Explorer registration, login/logout, role-based dashboards, and user profiles.
**Core feature:** Café check-ins (see [Core feature: Café check-ins](#core-feature-café-check-ins)).

## Local setup

For local development without PostgreSQL credentials, set `DJANGO_USE_SQLITE=1` in `.env`, together with a generated `DJANGO_SECRET_KEY` and `DJANGO_DEBUG=1`. This uses an ignored local `db.sqlite3` file. Install dependencies, then run `python manage.py migrate` and `python manage.py runserver`. Set `DJANGO_USE_SQLITE=0` to use the PostgreSQL configuration below; the two databases keep separate data.

1. Install Python 3.10+. If you use Supabase, get the PostgreSQL URI from the project's **Connect** panel and continue to step 2. If you run PostgreSQL 14+ locally, configure it to accept TLS connections and create a database and a login role that owns it. For example, in `psql` as a PostgreSQL administrator:

   ```sql
   CREATE ROLE matchatrail LOGIN;
   \password matchatrail
   CREATE DATABASE matchatrail OWNER matchatrail;
   ```

2. Open the extracted `MatchaTrail` directory and create a virtual environment.

   ```text
   python -m venv .venv
   ```

   Activate it with `.venv\Scripts\Activate.ps1` in PowerShell or `source .venv/bin/activate` in Bash. Then run:

   ```text
   python -m pip install -r requirements.txt
   python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
   ```

3. If you do not already have an `.env`, copy `.env.example` to `.env`. Set the generated value as a double-quoted `DJANGO_SECRET_KEY`. For PostgreSQL, set `DJANGO_USE_SQLITE=0` and set `DATABASE_URL` to your Supabase direct or session-pooler URI, or to your local PostgreSQL URI (`postgresql://matchatrail:PASSWORD@localhost:5432/matchatrail`). Replace placeholders and percent-encode any reserved characters in the password. Django requires TLS for PostgreSQL. Keep `.env` private.

4. Run `python manage.py migrate` and `python manage.py runserver`.
5. Open http://127.0.0.1:8000/register/ and create an Explorer account.

Run `python manage.py test` against a separate, disposable PostgreSQL development server/database using a role that can create test databases. Never point tests at a production or shared grading database. Use TLS as required by settings. Verify the active engine with `python manage.py shell -c "from django.db import connection; print(connection.vendor)"`. SQLite is not final PD3 database evidence.

## Role-based dashboards

Visit `/login/` after registering. Login always redirects to `/dashboard/`, which sends Explorers to `/dashboard/explorer/` and Café Owners to `/dashboard/owner/` based on their stored account role. Each dashboard has role-specific content and navigation. Anonymous visitors must log in; accessing another role's dashboard returns HTTP 403. Logout uses a CSRF-protected POST form.

The dashboards also show check-in data for each role (see Core feature below). Café discovery, saved places, and menu management remain planned features.

Public registration always creates Explorers. To prepare a Café Owner for a demo, register a second account and assign its role from the trusted Django shell:

```text
python manage.py shell
```

```python
from accounts.models import User
owner = User.objects.get(username="your_owner_username")
owner.role = User.Role.OWNER
owner.save(update_fields=["role"])
```

Sign in as each account in separate browser sessions to compare dashboards and try opening the other dashboard's URL.

The test suite covers registration validation, role assignment, login routing, role-specific rendering, cross-role access denial, invalid credentials, and logout.

## User profiles

After logging in, choose **My profile** in the navigation or visit `/profile/`. Both roles can view their own details and update their first name, last name, email, and contact number. Email addresses must be valid and unique regardless of case. Username and role are read-only. The server always uses the signed-in user; submitted account IDs and privilege fields cannot select another profile or change permissions. There are no public or per-user profile URLs. Profile tests cover anonymous access, updates, validation, account isolation, and CSRF protection.

## Core feature: Café check-ins

An Explorer records a visit to a café: the drink they tried, a 1-5 rating, an optional note, and the visit date. Check-ins are stored in PostgreSQL (Supabase) and shown on the role dashboards.

### Data model

- `Cafe`: name (unique), address, city (default Cebu City), price range (budget, mid-range, premium), description, active flag, and an optional owner (ForeignKey to User, Café Owner role only).
- `CheckIn`: belongs to a user (ForeignKey, deleted with the account) and a café (ForeignKey, protected from deletion while check-ins exist). Fields: drink name, rating (1-5), notes (up to 500 characters), visit date, and created/updated timestamps.

### CRUD operations

- **Create:** an Explorer adds a check-in with the form.
- **Read:** Explorers see their own check-ins; Café Owners see the check-ins left at their own cafés. Both appear on the role dashboards.
- **Update:** an Explorer can edit only their own check-ins.
- **Delete:** an Explorer can delete only their own check-ins, after a confirmation page.

### Validation and business rules

- Café, drink name, and rating are required; the rating must be 1-5 (checked in the form and by a database constraint).
- An Explorer can have only one check-in per café per day (database unique constraint plus a form error message).
- Clear success and error messages are shown after every action.

### Access control

- Only logged-in users can reach check-in pages; anonymous visitors are sent to log in.
- Users cannot view or change another user's check-ins. Accessing a page meant for another role returns HTTP 403.
- Every check-in is linked to the user who created it.

## Demo data and test accounts

On a disposable development or grading database, run the following command to create or refresh sample cafés and reset the demo accounts' passwords:

```text
python manage.py seed_demo
```

Create check-ins through the UI. The seed command assigns **Demo Matcha House** and **Demo Whisk & Leaf** to the demo Café Owner.

| Role | Username | Password |
|---|---|---|
| Explorer | `explorer_demo` | `Matcha!demo-2026` |
| Café Owner | `owner_demo` | `Matcha!demo-2026` |

## Branching

- `main`: stable code only, changed through pull requests.
- `develop`: integration branch.
- PD3 work branches: `fix/<issue>`, `hardening/<area>`, `test/<area>`; open pull requests into `develop`. Retain merged branches. Release via a pull request from `develop` into `main`; no direct main commits.
