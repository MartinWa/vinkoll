import os
import subprocess
import sys

from tools.check_runtime import check_runtime

if __name__ == "__main__":
    check_runtime()
    if os.getuid() == 0:
        raise RuntimeError("Use a non-root development user.")
    if sys.argv[1:2] == ["python"] and "runserver" in sys.argv:
        subprocess.run(["python", "manage.py", "migrate", "--noinput"], check=True)
    os.execvp(sys.argv[1], sys.argv[1:])
