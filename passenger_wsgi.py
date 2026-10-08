"""Phusion Passenger entry point (Hostido "Python app"). Serves the Telegram webhook from km_bot.web."""

import glob
import os
import site
import sys
import traceback

APP_DIR = os.path.dirname(os.path.abspath(__file__))

# 1. Add the project directory to sys.path
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

# 2. Include only the .venv site-packages matching Passenger's Python ABI.
# Pure-Python dependencies can appear to work across minor versions, while
# compiled extensions (PyMuPDF, ijson) fail with a misleading import error.
# Never add a site-packages directory from a different Python version.
runtime_python_dir = f"python{sys.version_info.major}.{sys.version_info.minor}"
venv_site_packages = os.path.join(APP_DIR, ".venv", "lib", runtime_python_dir, "site-packages")
available_venv_versions = glob.glob(os.path.join(APP_DIR, ".venv", "lib", "python*", "site-packages"))

venv_mismatch = None
if os.path.isdir(venv_site_packages):
    site.addsitedir(venv_site_packages)
elif available_venv_versions:
    available = ", ".join(os.path.basename(os.path.dirname(path)) for path in available_venv_versions)
    venv_mismatch = (
        "Passenger/.venv Python mismatch: Passenger uses "
        f"{sys.version_info.major}.{sys.version_info.minor}, but .venv contains: "
        f"{available}. Recreate .venv with the Passenger Python version."
    )

# 3. Safely import the application with error handling
try:
    if venv_mismatch:
        raise RuntimeError(venv_mismatch)
    from km_bot.web import application
except Exception:
    error_traceback = traceback.format_exc()
    print(error_traceback, file=sys.stderr, flush=True)

    def application(environ, start_response):
        output = b'{"status": "error", "detail": "startup failed, see the application stderr log"}'
        start_response(
            "500 Internal Server Error",
            [("Content-Type", "application/json"), ("Content-Length", str(len(output)))],
        )
        return [output]
