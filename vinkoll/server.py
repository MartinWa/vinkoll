import os

from django.core.management import call_command
from waitress import serve

from tools.check_runtime import check_runtime
from vinkoll.wsgi import application


def main():
    check_runtime()
    if os.getuid() == 0:
        raise RuntimeError("Run Vinkoll as a non-root UID/GID.")
    call_command("migrate", interactive=False)
    call_command("migrate", check=True, interactive=False)
    serve(
        application,
        host="0.0.0.0",
        port=8000,
        threads=4,
        # Allow a supported 20 MB photo plus multipart and ordinary form fields.
        max_request_body_size=22 * 1024 * 1024,
        # The listener is private to Caddy's Docker network. Trust only the scheme header.
        trusted_proxy="*",
        trusted_proxy_headers={"x-forwarded-proto"},
    )


if __name__ == "__main__":
    main()
