import os
import sys
from pathlib import Path


# PythonAnywhere should point its WSGI file at this module, or copy this file's
# contents into the PythonAnywhere-generated WSGI config.
PROJECT_DIR = Path(__file__).resolve().parent

if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

os.environ.setdefault("GENWISE_DATA_DIR", str(PROJECT_DIR / "genwise_classroom" / "instance"))

from genwise_classroom.app import app as application  # noqa: E402
