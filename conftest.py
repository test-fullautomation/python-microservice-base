"""Tests import MicroserviceBase from this checkout's python/ folder."""

import os
import sys

PYTHON_SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "python")
if PYTHON_SRC not in sys.path:
    sys.path.insert(0, PYTHON_SRC)
