# Vinkoll

A self-hosted wine cellar for a household or small group. Keep track of your wines, where each bottle is stored, what you paid, and what you have consumed.

The interface is Swedish and works on phones and desktops. Every active account shares the same catalogue and inventory. Wine details are entered manually, and all cellar data is stored locally.

## Features

- Wine profiles with producer, origin, grapes, bottle size, general notes, and optional Systembolaget product links.
- Individual bottles with a vintage, storage location, and purchase price.
- Location-filtered cellar views, bottle consumption, corrections, and moves.
- Local search across saved names, producers, origins, grapes and article numbers.
- Private phone photos, general notes, and dated reviews with 1–5 half-star scores.
- Gifts, losses, and inventory adjustments recorded separately from consumption.
- Inventory history and wine archiving/restoration that preserve existing bottles and history.
- Location archiving/reassignment and a shared preferred store name/ID.
- Separate Markdown snapshots of all wines/reviews and current bottles by location.
- Username/password sign-in, password changes, and operator-managed accounts.

Inventory changes and their history are saved together. Retrying a bottle addition or consumption does not repeat the change, and concurrent bottle edits are detected before saving. Forms preserve unsaved input after a session expires.

## Quick start

Install Docker with Compose. On Windows, use Docker Desktop with Linux containers.

```sh
docker compose -f compose.development.yaml up -d --build
docker compose -f compose.development.yaml exec vinkoll python manage.py setup_account your-username
```

Open <http://localhost:8003> and sign in. The account setup command prompts for a password; run it again with another username to create additional accounts.

This local configuration mounts the source checkout and stores the database in a Linux named volume. Stop it with `docker compose -f compose.development.yaml down`. The volume survives container replacement; adding `-v` to that command deletes its data.

To try the application with sample data:

```sh
docker compose -f compose.development.yaml exec vinkoll python manage.py seed_demo
```

Sign in with `demo` / `demo`. This optional command is available only in development and creates three example wines and six bottles. Running it again resets the demo account to these credentials.

## Using Vinkoll

1. **Viner → Lägg till vin** creates a wine profile. Enter its name, type, producer, origin, grapes, and bottle size. Saving a profile starts with zero bottles.
2. **Inställningar** creates or renames storage locations. Bottles without a location appear as **Utan plats**.
3. **Källare → Lägg till flaskor** adds bottles of an existing wine. Choose a location, quantity, actual vintage, and price paid per bottle. Leave an unknown price blank; zero is a valid price.
4. **Drick** consumes one bottle. When bottles differ by vintage, location, or price, select the group to consume from.
5. Open a wine in **Källare**, then use **Redigera flaska** to correct or move one bottle. **Historik** records additions, consumption, corrections, and moves.
6. **Viner** lets you edit, archive, restore, or delete profiles. Only unused profiles can be deleted. Archived wines with available bottles remain in Cellar; restore a profile before adding more bottles.
7. **Sök bland sparade viner** searches local records in Cellar or Wines, together with the current location/archive filter. Opening details and returning keeps that context.
8. Upload a photo in the wine editor. JPEG, PNG, WebP and HEIC/HEIF are supported, up to 20 MB and 40 megapixels. Photos are private, orientation is corrected, and display copies omit phone metadata. Choose the file again after an error or expired session; the remaining form input is preserved.
9. **Lägg till recension** saves a dated score and/or note separately. Scores use half-star steps from 1 to 5; blank is unrated. Earlier reviews remain in details and **Historik**, which filters by wine and action.
10. **Ta bort flaska** records a gift, loss or inventory adjustment. **Hantera plats** archives a location, moves its available bottles to another location or Unassigned, or restores it. Historical references are retained.

In **Inställningar → Skapa Markdown**, each section has its own Generate, raw-text preview and Copy action. **Alla viner, betyg och anteckningar** includes the full catalogue, archived/empty profiles, general notes and all reviews. **Aktuella flaskor** includes only available bottles within its own location scope, with grouped quantities and an explicit empty result. Both snapshots include the local timestamp/timezone and work without external services. If clipboard access is unavailable, select and copy the preview manually. Ordinary forms work without JavaScript; locally served HTMX keeps the two previews visible together when enabled.

The preferred Systembolaget store is currently entered as a name and ID; leading zeroes are preserved. Live store lookup and availability checks follow in stage 4, and product search/import follows in stage 3.

If a session expires while saving, sign in again to recover the form. Browser drafts stay in the current tab and exclude passwords. If another edit has changed a bottle, use **Kasta osparade uppgifter och ladda om** to discard your draft and load the current details.

## Self-hosting

Use a Linux Docker host and an HTTPS reverse proxy. The production Compose configuration connects Vinkoll to an existing Caddy network and stores persistent data in a host directory.

Copy [.env.example](.env.example) to `.env` and configure:

| Variable | Value |
| --- | --- |
| `VINKOLL_IMAGE` | Image tag or digest to run; use `vinkoll:local` for a local build |
| `VINKOLL_SECRET_KEY` | Private random key of at least 50 characters |
| `VINKOLL_ALLOWED_HOSTS` | Public hostname, without a scheme |
| `VINKOLL_CSRF_TRUSTED_ORIGINS` | Public HTTPS origin |
| `APP_UID`, `APP_GID` | Non-root UID/GID that own the data directory |
| `APP_DATA_PATH` | Host-local data directory, outside SMB/NFS or Windows mounts |
| `PROXY_NETWORK` | Existing Docker network shared with Caddy |

Generate a secret key with `python -c "import secrets; print(secrets.token_urlsafe(64))"`. Create the data directory and give the configured UID/GID ownership before starting.

```sh
docker compose build
docker compose up -d
docker compose exec vinkoll python manage.py setup_account your-username
```

Attach Caddy to `PROXY_NETWORK` and configure your hostname:

```caddyfile
wine.example.invalid {
    @health path /healthz/
    respond @health 404
    reverse_proxy vinkoll:8000
}
```

The application listener stays on the private Docker network. Caddy supplies HTTPS, and `/healthz/` is reserved for internal container checks.

The production container runs as a non-root user with a read-only filesystem, serves the application through Waitress, and applies migrations on startup. Persistent state is stored under `/data`. Back up the data directory while the application is stopped, and retain the matching image tag or digest with each backup before upgrading.

### Account management

Signed-in users change their passwords in **Inställningar**. To reset a password as the operator:

```sh
docker compose exec vinkoll python manage.py setup_account your-username --reset
```

A reset invalidates that account's existing sessions. Account creation and recovery use the same `setup_account` command; there is no public registration.

## Development and checks

Vinkoll uses Python 3.14, Django 5.2 LTS, server-rendered forms, and SQLite. Dependencies and container bases are pinned. The container verifies Python 3.14.10 and its linked SQLite 3.51.3. Rebuild after changing dependencies or the Dockerfile; `uv sync --locked` installs local Python tooling.

Run checks in the Linux development container:

```sh
docker compose -f compose.development.yaml exec -T vinkoll python -m ruff check .
docker compose -f compose.development.yaml exec -T vinkoll python -m ruff format --check .
docker compose -f compose.development.yaml exec -T vinkoll python manage.py makemigrations --check --dry-run
docker compose -f compose.development.yaml exec -T vinkoll python -m pytest
```

Build and smoke-test the production image:

```sh
docker build --target production -t vinkoll:local .
python tools/smoke.py vinkoll:local
```

The production smoke test uses temporary containers and a data volume to check authentication, CSRF, inventory retries, private photos, reviews, store settings, Markdown and persistence across container replacement. GitHub Actions runs these checks too.

For browser checks, seed the development demo and use the Playwright CLI:

```sh
playwright-cli -s=vinkoll open http://localhost:8003 --mobile
playwright-cli -s=vinkoll run-code --filename=tools/browser_smoke.js
playwright-cli -s=vinkoll run-code --filename=tools/browser_stage2_smoke.js
playwright-cli -s=vinkoll run-code --filename=tools/browser_nojs_smoke.js
playwright-cli -s=vinkoll close
```

Use a disposable demo instance for these scripts: they change synthetic inventory and the stage 2 script retains synthetic wine/review/history records. They check phone layouts at 390/320 px, form recovery, photo uploads, search, bottle operations, archive/restore, reviews, Markdown scopes, copying/fallback and operation without external requests. The final script verifies search, Markdown and location forms with JavaScript disabled. Screenshots are written to `test-results/`. Real-phone photo selection and NAS/Caddy verification remain release checks.

HTMX 2.0.8 is pinned and served locally; its license is in `static/vendor/htmx-LICENSE`. Evaluation, response scripts and private page-history caching are disabled to fit the application's CSP and authentication boundary.

### Translations

Application strings use English gettext messages and a Swedish `.po`/`.mo` catalogue. Swedish is the interface language regardless of browser preferences. Recompile the catalogue after editing translations:

```sh
uv run --with polib==1.2.0 python -c "import polib; polib.pofile('locale/sv/LC_MESSAGES/django.po', encoding='utf-8').save_as_mofile('locale/sv/LC_MESSAGES/django.mo')"
```
