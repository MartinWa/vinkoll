import platform
import sqlite3


def check_runtime():
    if platform.python_version() != "3.14.10":
        raise RuntimeError(f"Unexpected Python: {platform.python_version()}")
    if sqlite3.sqlite_version_info != (3, 51, 3):
        raise RuntimeError(f"Unexpected linked SQLite: {sqlite3.sqlite_version}")
    print(f"Python {platform.python_version()}, linked SQLite {sqlite3.sqlite_version} verified.")


if __name__ == "__main__":
    check_runtime()
