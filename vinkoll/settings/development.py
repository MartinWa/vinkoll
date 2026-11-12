from .base import *  # noqa: F403

DEBUG = True
SECRET_KEY = "development-only-not-for-production-00000000000000000000000000000000"
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]", "testserver", "vinkoll"]
DATA_DIR.mkdir(parents=True, exist_ok=True)  # noqa: F405
