import os
import sys


def get_base_path() -> str:
    if getattr(sys, "frozen", False):
        internal = os.path.join(os.path.dirname(sys.executable), "_internal")
        return internal if os.path.exists(internal) else os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(sys.argv[0]))
