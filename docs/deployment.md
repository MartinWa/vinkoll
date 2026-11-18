# Deployment

Vinkoll is deployed with a production Docker Compose configuration that connects
the application container to an existing Caddy network. Use a Linux Docker host
and an HTTPS reverse proxy; persistent state is stored in a host directory.

## Configure

Copy [.env.example](../.env.example) to `.env` and configure:

| Variable | Value |
| --- | --- |
| `VINKOLL_IMAGE` | Image tag or digest to run; use `vinkoll:local` for a local build |
| `VINKOLL_SECRET_KEY` | Private random key of at least 50 characters |
| `VINKOLL_ALLOWED_HOSTS` | Public hostname, without a scheme |
| `VINKOLL_CSRF_TRUSTED_ORIGINS` | Public HTTPS origin |
| `APP_UID`, `APP_GID` | Non-root UID/GID that own the data directory |
| `APP_DATA_PATH` | Host-local data directory, outside SMB/NFS or Windows mounts |
| `PROXY_NETWORK` | Existing Docker network shared with Caddy |

Generate a secret key with `python -c "import secrets; print(secrets.token_urlsafe(64))"`.
Create the data directory and give the configured UID/GID ownership before
starting.

## Initialize and start

```sh
docker compose build
docker compose up -d
docker compose exec vinkoll python manage.py setup_account your-username
```

Attach Caddy to `PROXY_NETWORK` and configure the hostname:

```caddyfile
wine.example.invalid {
    @health path /healthz/
    respond @health 404
    reverse_proxy vinkoll:8000
}
```

The application listener stays on the private Docker network. Caddy supplies
HTTPS, and `/healthz/` is reserved for internal container checks.

## Production runtime

The production container runs as a non-root user with a read-only filesystem,
serves the application through Waitress, and applies migrations on startup.
Persistent state is stored under `/data`: the SQLite database and uploaded
photos. Keep the data directory on storage local to the application host, not
on SMB/NFS or Windows mounts.

Do not publish the application port, and keep the installation on a private
LAN/VPN. See [SECURITY.md](../SECURITY.md) for the intended trust boundary.

## Account management

Signed-in users change their passwords in **Inställningar**. To reset a password
as the operator:

```sh
docker compose exec vinkoll python manage.py setup_account your-username --reset
```

A reset invalidates that account's existing sessions. Account creation and
recovery use the same `setup_account` command; there is no public registration.

## Upgrades

Before upgrading, back up the data directory as described in
[backup-and-recovery.md](backup-and-recovery.md) and retain the matching image
tag or digest with each backup. Pull or build the new `VINKOLL_IMAGE`, then
restart; migrations apply on startup.

A versioned image and release channel are planned; until then, build the image
locally from a known commit (`docker build --target production -t vinkoll:local .`)
and verify with `python tools/smoke.py vinkoll:local` before deploying.
