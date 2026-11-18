# Vinkoll

Cross-agent instructions for contributors and coding assistants working in this
repository.

## Read first

- [`README.md`](README.md) — current features, quick start and limitations.
- [`docs/usage.md`](docs/usage.md) — screen behavior, save retries and no-JavaScript fallbacks.
- [`docs/development.md`](docs/development.md) — checks, browser suite, translations and CI.
- [`docs/deployment.md`](docs/deployment.md) — Docker, private configuration and production runtime.
- [`docs/backup-and-recovery.md`](docs/backup-and-recovery.md) — manual backup and restore.
- [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE) — PolyForm Noncommercial 1.0.0, with the
  standard terms left unmodified.

## Scope and documentation ownership

The [README](README.md#features) is the source of truth for implemented features
and deliberate limitations; do not duplicate that inventory here. Do not
implement a feature outside the current scope without agreeing it with the
maintainer first. A planned feature is not an implemented capability.

Maintained documentation describes current behavior only. Keep each procedure in
one canonical guide and link to it rather than copying it. Do not add public
roadmap documents, milestone identifiers, changelogs or claims about verification
that has not been performed.

Keep the next-step checklist in the ignored private `planning/` directory when
available. Keep it concise and focused on remaining work; do not accumulate
planning history or verification logs there, and do not publish the planning
workspace or copy its status into maintained documentation.

## Language and publication

- Code, comments, identifiers, migrations, database table names and maintained
  documentation are in **English**.
- Swedish is the only interface locale. Use English source messages with the
  Swedish translation catalogue. Do not translate stored user-entered text.
- This repository is public. Keep personal wine records, photos, backups,
  credentials, hostnames, volume paths, proxy names and user/group IDs out of
  committed files. Use synthetic fixtures and generic examples.
- Never commit `.env` files, databases, media, backups or local tool state. Live
  state belongs in ignored directories (`data/`, `test-results/`) or private
  configuration.
- Licensing is **PolyForm Noncommercial 1.0.0**. Describe the project as
  source-available, not OSI open source. Keep the standard license text intact,
  preserve dependency notices, and do not add commercial-use exceptions or
  relicense without an explicit decision.

## Database and inventory integrity

- SQLite WAL is suitable for a small, shared installation **on a filesystem
  local to the application host**, not SMB/NFS storage mounted elsewhere. Keep
  transactions short and keep the configured timeout.
- Inventory changes and their history are saved together in short `IMMEDIATE`
  transactions (`cellar/services.py`). Do not split an inventory change from its
  event record.
- Every write produces an operation receipt; retrying a bottle addition or
  consumption must never repeat the change (`operation_receipt` tokens).
- Bottle edits use versions; a stale form must be rejected, not silently
  overwritten. Do not replace per-bottle inventory with an editable quantity
  field, and do not overwrite confirmed bottle vintages with provider data.
- Do not conflate the Systembolaget retail price with the purchase price.
- Database changes use Django migrations, never hand-edited production schemas.
- Django `save()` does not run `full_clean()`. Validate in the forms and
  services layer inside the transaction.

## UI and images

- Server-rendered forms and templates are the primary UI; HTMX is optional and
  pinned, served locally, and the application must keep working without it.
- No runtime CDN dependencies and no SPA or frontend build pipeline.
- Decode and re-encode uploaded JPEG, PNG, WebP and HEIC/HEIF images; enforce
  the upload size and pixel limits. Display derivatives must strip phone
  metadata; originals stay private and require authentication to view.
- Process images outside write transactions.
- Failed saves must be visible and retryable without dropping unsaved form
  input; browser drafts never include passwords.

## Integrations

The Systembolaget integration is validated but not yet part of the application
(Stages 3–4). Ordinary cellar functions must work with the provider absent. Use
direct backend adapters with bounded requests, persisted credentials-renewal,
caches and explicit stale/unavailable handling; see
`integrations/systembolaget/VALIDATION.md` for observed contracts. Never commit
discovered credentials. `tools/probe_systembolaget.py` is a live diagnostic and
never runs in CI.

## Implementation conventions

The application is split into `cellar` (wines, bottles, locations, history),
`core` (accounts, settings, operational commands) and `vinkoll` (settings and
server); add further modules only when a feature needs them. Run application
code only in the Linux development container as described in
[docs/development.md](docs/development.md#checks); the Windows host is for
editing. The development environment deliberately leaves `DJANGO_SETTINGS_MODULE`
unset so pytest uses the file-backed SQLite test settings needed for concurrency
checks.

Tests use `pytest-django` with real file-backed SQLite/WAL, not an in-memory
substitute. Run the Playwright browser scripts against a disposable seeded demo
instance, not real cellar data. Dependency changes must update `uv.lock` and
keep the lockfile consistent with the pinned Docker image digests.
