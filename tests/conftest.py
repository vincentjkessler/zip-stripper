"""Never touch the real clipboard during tests."""
import os

os.environ.setdefault("ZIPSTRIPPER_NO_CLIPBOARD", "1")
