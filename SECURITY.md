# Security

## Report a vulnerability

Use GitHub's [private vulnerability reporting](https://github.com/MartinWa/vinkoll/security/advisories/new).
Do not disclose vulnerabilities in public issues or pull requests before review.

Include the affected commit/version, impact, and a minimal reproduction using
synthetic data. Never attach real wine labels, photos, inventory records,
databases, backups, credentials or private host/proxy configuration. Test only
installations you own or have permission to test.

Security fixes target the current `main` branch and the latest release, when
available. Older versions are not maintained. This small project has no
guaranteed response or resolution time.

## Deployment boundary

Vinkoll is intended for private LAN/VPN access through HTTPS behind an existing
managed reverse proxy, not public Internet exposure. The application listener
stays on a private Docker network with no published port, and runs as a
non-root user with a read-only filesystem. Store the SQLite database and
uploaded photos only on storage local to the application host, not on SMB/NFS
shares. See [README.md](README.md) and
[docs/deployment.md](docs/deployment.md) for the supported setup.

## Application boundary

Authentication protects all application pages and cellar data; there is no
public registration. Every active account shares one cellar, and the operator
manages accounts and password resets. Do not add accounts for untrusted users.

Wine photos are private: display copies are stripped of phone metadata, and
originals are served only to signed-in users. The application serves its own
static assets, stores all data locally, and sends no telemetry. The planned
Systembolaget integration is the only outbound service; ordinary cellar
functions keep working without provider access. Operator-run live diagnostics
make outbound requests and must never run against production credentials.

## Vulnerable versions

Report and upgrade promptly when a Dependabot security update is offered:
Dependabot security alerts and the dependency-review, zizmor and pip-audit CI
checks are enabled for this repository. This project does not track CVEs
outside its dependency tree.
