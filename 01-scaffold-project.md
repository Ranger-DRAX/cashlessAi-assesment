# Step 1 — Scaffold the project

Read `AGENT.md` in the repo root first. Everything in it applies here.

## Objective

Stand up an empty-but-runnable Django + DRF project with the two apps this
project needs, ready for models in the next step.

## Requirements

- Create a Django project named `config` and two apps: `tenants` and
  `wallets`.
- Install and configure: `django`, `djangorestframework`, `psycopg2-binary`,
  `python-decouple` (or `django-environ`) for settings from environment
  variables.
- `settings.py`: register both apps and `rest_framework`; configure
  `DATABASES` to read host/name/user/password/port from environment
  variables, defaulting to a local Postgres instance.
- Set `REST_FRAMEWORK` defaults: `DEFAULT_PAGINATION_CLASS` (page-number or
  cursor pagination — cursor is preferable for an append-only ledger) and a
  sane `PAGE_SIZE` (20).
- Set up a local development environment: a virtualenv (or Poetry/pipenv,
  your choice) and a locally running Postgres — native install, or a bare
  `docker run postgres` one-liner if that's the easiest local Postgres you
  have, but do **not** write a `docker-compose.yml` or `Dockerfile` yet.
  Docker for the *application itself* is deliberately deferred to its own
  step after the app is feature-complete (see `09-dockerize.md`) — don't
  jump ahead to it here even if it feels natural to do both at once.
- Add a `requirements.txt` (or `pyproject.toml` if you prefer Poetry) pinned
  to specific versions, not floating.
- Add a `.env.example` documenting every environment variable the project
  reads.
- Add a `.gitignore` covering Python, Django, and editor artifacts.
- Do **not** create any models yet — that's step 2. This step ends with
  `python manage.py runserver` working against an empty project with no
  errors, against a locally running Postgres.

## Files to create

`config/` (settings, urls, wsgi/asgi), `tenants/` and `wallets/` as empty
Django apps (just `apps.py`, `__init__.py`, migrations folder), `manage.py`,
`requirements.txt`, `.env.example`, `.gitignore`, `README.md` (just a
one-line placeholder — the real README is step 8, and its Docker section
comes later still, in step 9).

## Acceptance criteria

- [ ] `python manage.py runserver` starts with no errors and no
      unapplied-migration warnings, against a locally running Postgres.
- [ ] `tenants` and `wallets` are both listed in `INSTALLED_APPS`.
- [ ] No secrets are hardcoded in `settings.py` — everything sensitive
      comes from environment variables, with `.env.example` documenting
      each one.
- [ ] `requirements.txt` versions are pinned, not left floating.

Commit as `feat: scaffold Django project with tenants and wallets apps`.