# Vinkoll

[![CI](https://github.com/MartinWa/vinkoll/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/MartinWa/vinkoll/actions/workflows/ci.yml)
[![OpenSSF Scorecard](https://api.securityscorecards.dev/projects/github.com/MartinWa/vinkoll/badge)](https://securityscorecards.dev/viewer/?uri=github.com/MartinWa/vinkoll)
[![License: PolyForm Noncommercial 1.0.0](https://img.shields.io/badge/license-PolyForm%20Noncommercial%201.0.0-blue)](LICENSE)
[![Python 3.14.10](https://img.shields.io/badge/python-3.14.10-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![Django 5.2 LTS](https://img.shields.io/badge/django-5.2%20LTS-092E20?logo=django&logoColor=white)](https://docs.djangoproject.com/en/5.2/)

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

## Scope and limitations

Vinkoll is intended for private, trusted use behind an HTTPS reverse proxy, with accounts only for the household or small group sharing the cellar. Live Systembolaget product search/import and store availability checks are planned but not part of the application yet; the preferred store is currently a name and ID. A versioned image and release channel, scheduled backups, and a NAS deployment guide are planned. See [docs/usage.md](docs/usage.md) for current screen behavior.

## Requirements

- A Linux Docker host (Windows with Docker Desktop and Linux containers works for development and testing).
- Docker with Compose.
- For production: an existing Caddy instance (or similar HTTPS reverse proxy) and a host-local data directory.

## Quick start

```sh
docker compose -f compose.development.yaml up -d --build
docker compose -f compose.development.yaml exec vinkoll python manage.py setup_account your-username
```

Open <http://localhost:8003> and sign in. The account setup command prompts for a password; run it again with another username to create additional accounts.

To try the application with sample data:

```sh
docker compose -f compose.development.yaml exec vinkoll python manage.py seed_demo
```

Sign in with `demo` / `demo`. This optional command is available only in development and creates three example wines and six bottles. Running it again resets the demo account to these credentials.

## Documentation

- [Usage](docs/usage.md) — screens, bottle workflows, photos, reviews, Markdown snapshots, save retries and sign-in.
- [Deployment](docs/deployment.md) — production Compose configuration, Caddy, runtime and account management.
- [Development](docs/development.md) — container checks, smoke tests, browser suite, translations, CI and dependency updates.
- [Backup and recovery](docs/backup-and-recovery.md) — manual backup, verification and restore of the data directory.
- [Security](SECURITY.md) — private vulnerability reporting and the intended deployment boundary.
- `integrations/systembolaget/VALIDATION.md` — recorded Systembolaget integration contracts and the adapter choice.

## Project layout

- `cellar/` — wines, bottles, locations, history, services and views.
- `core/` — accounts, settings, operational and management commands.
- `vinkoll/` — project settings and the Waitress production server.
- `integrations/` — recorded external integration contracts and validation notes.
- `tools/` — smoke tests, browser check scripts and live diagnostics.
- `tests/` — database and web tests.

## Security

Vinkoll is intended for private LAN/VPN access through HTTPS. Report vulnerabilities privately; see [SECURITY.md](SECURITY.md).

## License

[PolyForm Noncommercial License 1.0.0](LICENSE) — source-available software, not OSI open source. See [NOTICE](NOTICE) for attribution details.
