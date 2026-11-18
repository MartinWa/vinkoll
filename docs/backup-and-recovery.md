# Backup and recovery

All persistent state is stored under one data directory: the SQLite database and
uploaded wine photos. Scheduled, verified backups are planned; the supported
procedure below is manual. Verify a backup can be restored on a clean instance
before entering real cellar data.

## What to back up

- The contents of the configured data directory (`APP_DATA_PATH` in production,
  the `development-data` volume in development): the SQLite database and photo
  files.
- The matching image tag or digest, so a backup can be restored with the
  application version that created it.
- The `.env` deployment configuration, kept outside the data directory and
  protected separately.

## Back up

Stop the application first so the SQLite database is closed and the snapshot is
consistent, then copy the data directory:

```sh
docker compose down
tar -czf vinkoll-data-$(date -u +%Y%m%d-%H%M%S).tar.gz "$APP_DATA_PATH"
docker compose up -d
```

For the development container, stop and copy the volume contents instead, or
back up the volume with a one-off container:

```sh
docker compose -f compose.development.yaml down
docker run --rm --volume vinkoll-development-data:/data --volume "$PWD:/backup" \
  alpine tar -czf /backup/development-data.tar.gz -C /data .
```

Do not back up a live SQLite database by copying its database file during
active use.

## Verify a backup

Restore the backup into a clean data directory and known image tag, start the
container, sign in, and confirm the catalogue, bottle counts, history and photos
are present:

```sh
tar -xzf vinkoll-data-YYYYMMDD-HHMMSS.tar.gz -C "$APP_DATA_PATH"
docker compose up -d
```

## Restore to the running installation

Stop the application, replace the data directory contents with the verified
backup, and restart with the retained image tag or digest. Migrations only run
forward; restore with the matching image rather than downgrading.

## Retention

Keep at least two verified generations, stored outside the application host or
on separate storage, and protected at rest. Delete superseded backups only after
the newer generation has been verified with a clean restore.
