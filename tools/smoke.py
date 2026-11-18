"""Exercise a production image over HTTP and retain data across container replacement.

Only isolated, randomly named Docker resources and synthetic accounts are created.
The local test listener emulates Caddy's trusted HTTPS header; production exposes no host port.
"""

import base64
import hashlib
import html
import http.cookiejar
import re
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from uuid import uuid4


def docker(*args):
    return subprocess.check_output(["docker", *args], text=True).strip()


def main(image):
    name = "vinkoll-smoke-" + uuid4().hex[:12]
    volume = name + "-data"
    secret = secrets.token_urlsafe(64)
    containers = []
    docker("volume", "create", volume)
    try:

        def start(suffix):
            container = name + suffix
            docker(
                "run",
                "-d",
                "--name",
                container,
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges:true",
                "--tmpfs",
                "/tmp:size=67108864",
                "--mount",
                f"type=volume,src={volume},dst=/data",
                "-p",
                "127.0.0.1::8000",
                "-e",
                "VINKOLL_ALLOWED_HOSTS=localhost",
                "-e",
                "VINKOLL_CSRF_TRUSTED_ORIGINS=https://localhost",
                "-e",
                f"VINKOLL_SECRET_KEY={secret}",
                image,
            )
            containers.append(container)
            port = docker("port", container, "8000/tcp").rsplit(":", 1)[1]
            base = f"http://127.0.0.1:{port}"
            jar = http.cookiejar.CookieJar()
            opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

            def request(path, data=None, *, csrf=False, content_type=None, binary=False):
                headers = {
                    "Host": "localhost",
                    "X-Forwarded-Proto": "https",
                    "Origin": "https://localhost",
                }
                if data is not None:
                    if csrf:
                        # Secure cookies cannot be sent by the HTTP test client automatically.
                        cookies = {cookie.name: cookie.value for cookie in jar}
                        headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in cookies.items())
                        headers["X-CSRFToken"] = cookies["csrftoken"]
                    if not isinstance(data, bytes):
                        data = urllib.parse.urlencode(data).encode()
                    if content_type:
                        headers["Content-Type"] = content_type
                else:
                    headers["Cookie"] = "; ".join(f"{c.name}={c.value}" for c in jar)
                req = urllib.request.Request(base + path, data=data, headers=headers)
                try:
                    with opener.open(req, timeout=5) as response:
                        body = response.read()
                        return response.status, body if binary else body.decode(), response.headers
                except urllib.error.HTTPError as error:
                    return error.code, error.read().decode(), error.headers

            for _ in range(40):
                try:
                    if request("/healthz/")[0] == 200:
                        return container, request
                except urllib.error.URLError, ConnectionError:
                    pass
                time.sleep(0.25)
            raise RuntimeError(docker("logs", container))

        container, request = start("-first")
        assert request("/")[1].find("Logga in") >= 0
        docker(
            "exec",
            container,
            "python",
            "manage.py",
            "shell",
            "-c",
            "from django.contrib.auth import get_user_model; "
            "get_user_model().objects.create_user('smoke', password='synthetic-smoke-secret-1928')",
        )

        def login(request):
            request("/accounts/login/")
            response = request(
                "/accounts/login/",
                {
                    "username": "smoke",
                    "password": "synthetic-smoke-secret-1928",
                },
                csrf=True,
            )
            assert response[0] == 200, response[1]
            assert "Källare" in request("/")[1]

        login(request)
        assert (
            request(
                "/wines/add/",
                {
                    "name": "Synthetic smoke wine",
                    "wine_type": "red",
                    "volume_ml": "750",
                },
                csrf=True,
            )[0]
            == 200
        )
        page = request("/bottles/add/")[1]
        wine_id = re.search(r'<option value="(\d+)"[^>]*>Synthetic smoke wine', page).group(1)
        data = {
            "token": str(uuid4()),
            "wine": wine_id,
            "quantity": "2",
            "vintage_kind": "year",
            "vintage_year": "2021",
            "purchase_price": "0",
        }
        assert request("/bottles/add/", data, csrf=True)[0] == 200
        assert request("/bottles/add/", data, csrf=True)[0] == 200
        assert "2 tillgängliga flaskor" in request("/")[1]
        token = html.unescape(re.search(r'name="token" value="([^"]+)"', request("/")[1]).group(1))
        assert request(f"/wines/{wine_id}/consume/", {"token": token}, csrf=True)[0] == 200
        assert "1 tillgänglig flaska" in request("/")[1]
        assert (
            request(
                f"/wines/{wine_id}/reviews/add/",
                {
                    "token": str(uuid4()),
                    "date": "2026-11-10",
                    "score": "3.5",
                    "notes": "Synthetic dated review",
                },
                csrf=True,
            )[0]
            == 200
        )
        assert (
            request(
                "/settings/store/", {"store_id": "0012", "store_name": "Synthetic store"}, csrf=True
            )[0]
            == 200
        )

        # Uncompressed pixels and a small PNG text chunk fill the 20 MB limit exactly.
        photo = base64.b64decode(
            docker(
                "exec",
                container,
                "python",
                "-c",
                "import base64, io; from PIL import Image; from PIL.PngImagePlugin import PngInfo; "
                "source = Image.new('RGB', (2048, 3410), 'purple'); "
                "output = io.BytesIO(); "
                "source.save(output, 'PNG', compress_level=0); "
                "metadata = PngInfo(); "
                "metadata.add_text('Padding', 'x' * (20 * 1024 * 1024 - output.tell() - 20)); "
                "output = io.BytesIO(); "
                "source.save(output, 'PNG', compress_level=0, pnginfo=metadata); "
                "assert output.tell() == 20 * 1024 * 1024; "
                "print(base64.b64encode(output.getvalue()).decode())",
            )
        )
        assert len(photo) == 20 * 1024 * 1024

        def upload_photo(contents, **extra):
            boundary = "vinkoll-smoke-" + uuid4().hex
            parts = []
            for key, value in {
                "name": "Synthetic smoke wine",
                "wine_type": "red",
                "volume_ml": "750",
                "notes": "Synthetic general notes\nSecond line",
                **extra,
            }.items():
                parts.append(
                    (
                        f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"'
                        f"\r\n\r\n{value}\r\n"
                    ).encode()
                )
            parts += [
                f'--{boundary}\r\nContent-Disposition: form-data; name="photo"; '
                'filename="phone.png"\r\n'
                "Content-Type: image/png\r\n\r\n".encode(),
                contents,
                f"\r\n--{boundary}--\r\n".encode(),
            ]
            return request(
                f"/wines/{wine_id}/edit/",
                b"".join(parts),
                csrf=True,
                content_type=f"multipart/form-data; boundary={boundary}",
            )

        response = upload_photo(photo)
        assert response[0] == 200, response[1]
        image_url = html.unescape(re.search(r'<img src="([^"]+)"', request("/")[1]).group(1))
        image_response = request(image_url, binary=True)
        assert image_response[0] == 200 and image_response[2]["Content-Type"] == "image/webp"
        image_checksum = hashlib.sha256(image_response[1]).hexdigest()

        response = upload_photo(photo + b"x", notes="Preserved oversize notes")
        assert response[0] == 200, response[1]
        assert 'id="id_photo_error"' in response[1]
        assert "Preserved oversize notes" in response[1]

        def assert_stage2(request):
            assert "3,5/5" in request("/")[1]
            assert 'value="0012"' in request("/settings/")[1]
            catalogue = html.unescape(request("/settings/markdown/wines/", {}, csrf=True)[1])
            assert "Synthetic general notes" in catalogue and "Synthetic dated review" in catalogue
            assert "3.5/5" in catalogue
            current = request("/settings/markdown/bottles/", {"location": "all"}, csrf=True)[1]
            assert "Available bottles in this scope: 1" in current
            assert hashlib.sha256(request(image_url, binary=True)[1]).hexdigest() == image_checksum

        assert_stage2(request)
        assert request(f"/wines/{wine_id}/consume/", {"token": token}, csrf=True)[0] == 200
        assert "1 tillgänglig flaska" in request("/")[1]
        assert request("/accounts/logout/", {}, csrf=True)[0] == 200
        assert "Logga in" in request("/")[1]
        docker("stop", container)
        _replacement, request = start("-replacement")
        login(request)
        assert "1 tillgänglig flaska" in request("/")[1]
        assert "Synthetic smoke wine" in request("/timeline/")[1]
        assert_stage2(request)
        print(
            "Production smoke passed: login, CSRF, inventory retries, 20 MB private photos, "
            "oversize upload recovery, reviews, "
            "store settings, Markdown, logout, persistence across container replacement."
        )
    finally:
        for container in containers:
            subprocess.run(["docker", "rm", "-f", container], capture_output=True, check=False)
        subprocess.run(["docker", "volume", "rm", volume], capture_output=True, check=False)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "vinkoll:local")
