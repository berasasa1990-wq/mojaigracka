# Mojaigracka — Render

Service: Python 3, repository berasasa1990-wq/mojaigracka, root directory empty.
Python: .python-version selects the latest Python 3.14 patch.

Build Command:
```sh
python -m pip install -r requirements.txt && python manage.py collectstatic --noinput
```
Start Command:
```sh
python -m gunicorn OnlineShopProject.wsgi:application --bind 0.0.0.0:$PORT --workers 2 --access-logfile - --error-logfile -
```

## Environment variables

- DJANGO_ENV=production
- DEBUG=false
- SECRET_KEY: generate a new random value (at least 50 characters) in Render.
  Never reuse the old development key or commit this value.
- DATABASE_URL: Internal Database URL of a NEW PostgreSQL database belonging only
  to Mojaigracka. Never use CarpologijaBH. Production requires PostgreSQL and SSL.
- ALLOWED_HOSTS: actual hostname(s), comma separated, without https:// or paths.
  Render automatically supplies RENDER_EXTERNAL_HOSTNAME; settings include it.
  Add custom domains explicitly. Do not use a wildcard.
- CSRF_TRUSTED_ORIGINS: https://actual-host.onrender.com and any custom HTTPS
  origins, comma separated. The Render hostname is also included automatically.
- MEDIA_ROOT=/var/data/media (attach a persistent Render disk at /var/data).

Do not guess your Render hostname: copy it from the created service.
Do not define RENDER_EXTERNAL_HOSTNAME manually on Render.

## Data and first release

Build does NOT run migrations. After reviewing a database backup, manually run:
```sh
python manage.py migrate
python manage.py createsuperuser
```
Run migrations once per release when needed, using Render Shell or a controlled
pre-deploy step. Review pending migrations before running them. No migrations
or exports of the local SQLite database were performed by this preparation.

A new PostgreSQL database starts EMPTY. Plan and validate transfer of existing
SQLite data separately before directing customers to it. Copy existing media
into the persistent MEDIA_ROOT and verify product/banner images. WhiteNoise
serves static assets; existing /media/ routes continue to serve uploaded images.
Free/ephemeral filesystem storage is unsuitable for uploaded product images.
Existing SQLite-specific backup/restore tools do not back up PostgreSQL: enable
PostgreSQL backups and a separate media backup policy. Do not use SQLite restore
operations against production PostgreSQL.

HSTS remains disabled intentionally. Check real HTTPS, redirects, cookies,
custom domains, CSRF forms, uploads, checkout, login and static files after deploy
before considering enabling it. check --deploy will report security.W004 until
HSTS is deliberately configured.

## Optional existing integrations

Configure SMTP (EMAIL_HOST, EMAIL_PORT, EMAIL_HOST_USER, EMAIL_HOST_PASSWORD,
EMAIL_USE_TLS or EMAIL_USE_SSL, DEFAULT_FROM_EMAIL) to send notifications.
If used, provision ADMIN_SSO_KEY, MODULE_CONTROL_KEY and the existing
BERA_LICENSE_* variables as secrets. Preserve BERA_LICENSE_ENCRYPTION_KEY when
moving encrypted credentials. Never copy another project's credentials.
Existing external licensing settings were preserved; no remote activation or
CarpologijaBH connection is part of deployment preparation.

## Local checks

Django does not auto-load .env. For example:
```sh
DJANGO_ENV=development DEBUG=true venv/bin/python manage.py runserver
DJANGO_ENV=development DEBUG=true venv/bin/python manage.py check
DJANGO_ENV=development DEBUG=true venv/bin/python manage.py test --noinput
```
Local development keeps db.sqlite3. Production fails closed without a strong
SECRET_KEY, explicit allowed hostname and PostgreSQL DATABASE_URL. Render refuses
development mode; production refuses DEBUG=true. No push/deploy was performed.

## Validation during preparation (2026-10-27)

- manage.py check: passed.
- manage.py check --deploy using dummy production secrets/PostgreSQL URL: passed
  with expected security.W004 (HSTS intentionally disabled). No DB connection.
- Production collectstatic --noinput: passed, 184 static source files total.
  Added eight missing Inter WOFF2 assets and their OFL license; CSS unchanged.
- Existing suite: 265 tests, 264 passed, 1 failure:
  shop.test_premium_seo.PremiumSeoPanelTests.test_locked_access_and_settings_moved.
  It expects “Uredi SEO postavke” in the modules panel. It passes in isolation;
  the full suite reproduces the same failure with WhiteNoise removed. Resolve
  this order-dependent test/application state issue before production approval.
- Production WSGI static requests for homepage assets and fonts: HTTP 200.
- Homepage, cart, wishlist, robots and sitemap: HTTP 200 on a disposable local
  database snapshot; anonymous account route redirects as expected.
- HTTP redirects to HTTPS. Invalid production settings fail closed.
- Local db.sqlite3 SHA-256 unchanged across validation.
- No tracked ignored artifacts found; no Git index removal was necessary.
- pip check and git diff --check: passed.

Limitations: no live PostgreSQL, real Render hostname, HTTPS certificate, SMTP
or browser visual verification was exercised. Runtime smoke checks used a
throwaway SQLite snapshot with test-only settings overrides. Production settings
continue to forbid SQLite. No push, deployment or local migration occurred.
Existing unrelated local modifications and untracked application/migration files
were preserved. Include all intended application files in the reviewed commit
before deploying; do not commit local secrets, SQLite, media or staticfiles.

## Diagnosing HTTP 500 after first deploy

Django tracebacks now go to stderr/Render application logs even with DEBUG=false.
The SQLite-only hourly backup worker is skipped on PostgreSQL; use PostgreSQL
backups supplied by the database provider. A backup-thread exception by itself
is not the traceback of an HTTP request.

On the first release, inspect `python manage.py showmigrations --plan` in Render
Shell. If the new Mojaigracka database has pending migrations, review them and
run `python manage.py migrate` manually. Do not leave migrations in the regular build
command. For a one-time free-plan setup without Shell, see below. A `relation ... does not exist` request traceback indicates missing
tables/migrations; other exceptions need their own diagnosis. Keep DEBUG=false.

## Free plan: one-time migration without Shell

For the first setup of the dedicated Mojaigracka PostgreSQL database only, use
this temporary Build Command in the Render dashboard:

```sh
python -m pip install -r requirements.txt && python manage.py collectstatic --noinput && python manage.py migrate --noinput
```

Review the database target and pending migrations first. For an existing database,
take a backup before applying changes. Trigger the deploy manually. Verify the
build log contains successful migration results and test the homepage. Afterwards
restore the regular Build Command immediately:

```sh
python -m pip install -r requirements.txt && python manage.py collectstatic --noinput
```

Keep the existing Gunicorn Start Command. This is a temporary operator-controlled
step, not automatic migration on every build. No local SQLite data is transferred
by migrate. If HTTP 500 persists, inspect its request traceback rather than
assuming the schema is the only cause.

## Activate this project's local environment

From the MojaIgracka root, run `source ./dev.sh` in each new terminal.
This selects this project's venv, enables development mode, and unsets
DATABASE_URL so local commands use this project's SQLite only. It does not
connect to Render or another project. Then run `python manage.py createsuperuser`
interactively if a LOCAL admin account is needed. The VS Code workspace defaults
to venv/bin/python. Virtual environments should be recreated after moving a
project; do not commit the venv directory.
