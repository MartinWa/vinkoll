# Development

Vinkoll uses Python 3.14, Django 5.2 LTS, server-rendered forms, and SQLite.
The application and its checks run in a Linux development container; the Windows
host is for editing. Dependencies and container bases are pinned, and the image
build verifies Python 3.14.10 and its linked SQLite 3.51.3. Rebuild after
changing dependencies or the Dockerfile; `uv sync --locked` installs local Python
tooling.

## Start the development container

```sh
docker compose -f compose.development.yaml up -d --build
```

Open <http://localhost:8003> and create an account:

```sh
docker compose -f compose.development.yaml exec vinkoll python manage.py setup_account your-username
```

The database is stored in a Linux named volume that survives container
replacement. Stop with `docker compose -f compose.development.yaml down`; adding
`-v` deletes its data.

Optional sample data is available in development only. Running it again resets
the demo account to these credentials:

```sh
docker compose -f compose.development.yaml exec vinkoll python manage.py seed_demo
```

Sign in with `demo` / `demo`.

## Checks

Run lint, formatting, migration and test checks in the container:

```sh
docker compose -f compose.development.yaml exec -T vinkoll python -m ruff check .
docker compose -f compose.development.yaml exec -T vinkoll python -m ruff format --check .
docker compose -f compose.development.yaml exec -T vinkoll python manage.py makemigrations --check --dry-run
docker compose -f compose.development.yaml exec -T vinkoll python -m pytest
```

Leave `DJANGO_SETTINGS_MODULE` unset so pytest uses `vinkoll.settings.test`,
which uses a file-backed SQLite database for the concurrency tests. Setting it
to development while testing can switch to an in-memory test database and
invalidate concurrency checks.

## Production smoke test

Build and smoke-test the production image with temporary containers and a
data volume:

```sh
docker build --target production -t vinkoll:local .
python tools/smoke.py vinkoll:local
```

The smoke test checks HTTP authentication, CSRF, inventory retries, private
photos, reviews, store settings, Markdown and persistence across container
replacement.

## Browser checks

Seed the development demo first, then use the Playwright CLI against a
disposable instance — these scripts change synthetic inventory:

```sh
playwright-cli -s=vinkoll open http://localhost:8003 --mobile
playwright-cli -s=vinkoll run-code --filename=tools/browser_smoke.js
playwright-cli -s=vinkoll run-code --filename=tools/browser_stage2_smoke.js
playwright-cli -s=vinkoll run-code --filename=tools/browser_nojs_smoke.js
playwright-cli -s=vinkoll close
```

They check phone layouts at 390/320 px, form recovery, photo uploads, local
search, bottle operations, archive/restore, reviews, Markdown scopes,
copying/fallback and operation without external requests. The final script
verifies search, Markdown and location forms with JavaScript disabled.
Screenshots are written to `test-results/`. Real-phone photo selection and
NAS/Caddy verification remain release checks.

## Translations

Application strings use English gettext messages and a Swedish `.po`/`.mo`
catalogue. Swedish is the interface language regardless of browser preferences.
Recompile the catalogue after editing translations:

```sh
uv run --with polib==1.2.0 python -c "import polib; polib.pofile('locale/sv/LC_MESSAGES/django.po', encoding='utf-8').save_as_mofile('locale/sv/LC_MESSAGES/django.mo')"
```

## CI and dependency updates

GitHub Actions runs on every pull request and push to `main`, plus a weekly
scheduled run, and additionally audits workflow security (zizmor), dependency
changes on pull requests (dependency review) and locked Python dependencies for
known vulnerabilities (pip-audit across all locked dependencies including dev).
See [.github/workflows/ci.yml](../.github/workflows/ci.yml) for the current job
set: **Checks (Linux)** builds the development image and runs lint, formatting,
migration and test checks; **Container (Linux)** validates workflow syntax,
audits locked dependencies, builds the production image and runs the HTTP and
persistence smoke test.

Dependabot opens weekly update pull requests for Python (`uv`), GitHub Actions
and Docker base images, with a cooldown for non-security updates and automatic
merge for Dependabot-committed patch updates that pass the required checks.
Steer dependency changes through `uv` and keep `uv.lock` consistent; stay on
Django 5.2 LTS.

## Live integration diagnostics

`tools/probe_systembolaget.py` is an explicit live diagnostic against the
Systembolaget backend and never runs in CI. It must not be run against
production credentials or a production installation. See
[integrations/systembolaget/VALIDATION.md](../integrations/systembolaget/VALIDATION.md)
for the recorded contracts, and `compose.systembolaget.example.yaml` for the
optional standalone helper diagnostic.
