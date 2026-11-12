import os

from .development import *  # noqa: F403

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
WHITENOISE_AUTOREFRESH = True
# A real file is required for separate-thread SQLite concurrency tests.
DATABASES["default"]["TEST"] = {  # noqa: F405
    "NAME": os.environ.get("VINKOLL_TEST_DB", str(DATA_DIR / "test.sqlite3")),  # noqa: F405
}
