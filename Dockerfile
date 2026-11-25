# syntax=docker/dockerfile:1
FROM ghcr.io/astral-sh/uv:0.13.10@sha256:a3ea1357342c1a4bf9a0c53a3deb1b55379aefa037338d8113d5771efa01774f AS uv-bin
FROM python:3.14.10-slim-bookworm@sha256:3fe1a0b6c2d6b2ebb572906cdabeca75aeb558c0c17db5ffefbcf8094871c32b AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

# Bookworm's stock SQLite predates the WAL-reset fix. Build the verified fixed library.
FROM base AS sqlite-build
RUN apt-get update && apt-get install -y --no-install-recommends build-essential ca-certificates \
    && rm -rf /var/lib/apt/lists/*
ADD --checksum=sha256:81f5be397049b0cae1b167f2225af7646fc0f82e4a9b3c48c9ea3a533e21d77a \
    https://www.sqlite.org/2026/sqlite-autoconf-3510300.tar.gz /tmp/sqlite.tar.gz
RUN tar -xzf /tmp/sqlite.tar.gz -C /tmp \
    && cd /tmp/sqlite-autoconf-3510300 \
    && ./configure --prefix=/opt/sqlite --enable-threadsafe --disable-static \
    && make -j2 && make install

FROM base AS dependencies
COPY --from=uv-bin /uv /bin/uv
WORKDIR /build
COPY pyproject.toml uv.lock ./
RUN uv export --locked --no-dev --no-emit-project -o /tmp/requirements.txt \
    && python -m pip install --no-cache-dir --require-hashes --prefix=/opt/python -r /tmp/requirements.txt

FROM base AS runtime
ENV LD_LIBRARY_PATH=/opt/sqlite/lib VINKOLL_DATA_DIR=/data
COPY --from=sqlite-build /opt/sqlite/lib /opt/sqlite/lib
COPY --from=dependencies /opt/python /usr/local
WORKDIR /app
RUN mkdir /data && chown 1000:1000 /data
COPY tools/check_runtime.py /app/tools/check_runtime.py
RUN python /app/tools/check_runtime.py

FROM runtime AS development
COPY --from=uv-bin /uv /bin/uv
COPY pyproject.toml uv.lock ./
RUN uv export --locked --only-group dev --no-emit-project -o /tmp/dev-requirements.txt \
    && python -m pip install --no-cache-dir --require-hashes -r /tmp/dev-requirements.txt
ENV RUFF_CACHE_DIR=/tmp/ruff \
    PYTEST_ADDOPTS="-o cache_dir=/tmp/pytest-cache"
COPY . /app
USER 1000:1000
ENTRYPOINT ["python", "-m", "tools.dev_entrypoint"]
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]

FROM runtime AS production
ENV DJANGO_SETTINGS_MODULE=vinkoll.settings.production
COPY manage.py /app/manage.py
COPY vinkoll /app/vinkoll
COPY cellar /app/cellar
COPY core /app/core
COPY integrations /app/integrations
COPY templates /app/templates
COPY static /app/static
COPY locale /app/locale
COPY tools/__init__.py /app/tools/__init__.py
RUN VINKOLL_SECRET_KEY=synthetic-build-only-key-never-use-for-runtime-00000000000000000000 \
    VINKOLL_ALLOWED_HOSTS=build.invalid VINKOLL_CSRF_TRUSTED_ORIGINS=https://build.invalid \
    python manage.py collectstatic --noinput
USER 1000:1000
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s \
    CMD python -c "import urllib.request; r=urllib.request.Request('http://127.0.0.1:8000/healthz/', headers={'Host': __import__('os').environ['VINKOLL_ALLOWED_HOSTS'].split(',')[0]}); urllib.request.urlopen(r, timeout=3)"
CMD ["python", "-m", "vinkoll.server"]
