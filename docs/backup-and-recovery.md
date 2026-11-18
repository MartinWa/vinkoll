# Backup and recovery

All persistent state is stored under one data directory: the SQLite database and
uploaded wine photos. Scheduled, verified backups are planned; the supported
procedure below is manual. Verify a backup can be restored on a clean instance
before entering real cellar data.

Production commands use the `.env` values configured for deployment. Load them
into the shell first — Compose reads `.env` itself, but `tar` does not:

```sh
cd /path/to/vinkoll
set -a && . ./.env && set +a
```

If the variables are managed another way, substitute the actual data-directory
path for `$APP_DATA_PATH` in the commands below.

## What to back up

- The contents of the configured data directory (`APP_DATA_PATH` in production,
  the `development-data` volume in development): the SQLite database and photo
  files.
- The matching image tag or digest, so a backup can be restored with the
  application version that created it.
- The `.env` deployment configuration, kept outside the data directory and
  protected separately.

## Back up (production)

Stop the application so the SQLite database is closed and the snapshot is
consistent, archive the *contents* of the data directory, and start again:

```sh
docker compose down
tar -czf "vinkoll-data-$(date -u +%Y%m%d-%H%M%S).tar.gz" -C "$APP_DATA_PATH" .
docker compose up -d
```

Do not back up a live SQLite database by copying its database file during
active use.

## Back up (development)

The volume is owned by the Compose project, so let Compose resolve its name
and read it through a one-off service container. Stop the development stack
first:

```sh
docker compose -f compose.development.yaml down
docker compose -f compose.development.yaml run --rm \
  --volume "$PWD:/backup" vinkoll \
  tar -czf /backup/development-data.tar.gz -C /data .
```

## Verify a backup

Restore the archive into a clean data directory and run the matching image tag,
start the container, sign in, and confirm the catalogue, bottle counts, history
and photos are present. The archive stores the data-directory contents, so it
extracts into the data directory as-is:

```sh
tar -xzf vinkoll-data-YYYYMMDD-HHMMSS.tar.gz -C "$APP_DATA_PATH"
docker compose up -d
```

## Restore to the running installation

Stop the application, clear the data directory, extract the verified backup, and
restart with the retained image tag or digest:

```sh
docker compose down
find "$APP_DATA_PATH" -mindepth 1 -delete
tar -xzf vinkoll-data-YYYYMMDD-HHMMSS.tar.gz -C "$APP_DATA_PATH"
docker compose up -d
```

Migrations only run forward; restore with the matching image rather than
downgrading.

## Retention

Keep at least two verified generations, stored outside the application host or
on separate storage, and protected at rest. Delete superseded backups only after
the newer generation has been verified with a clean restore.
