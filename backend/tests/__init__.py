"""Test setup, pinned before any test module imports the system.

The data store is redirected to a temp directory so the suite does not append
fixtures to the demonstration's ledger, and the agent adapter is disabled so
the suite stays offline. `RAMIFY_TEST_LIVE_MODEL=1` opts back in.
"""

import atexit
import os
import shutil
import tempfile
from pathlib import Path

_TEMP_STORE = Path(tempfile.mkdtemp(prefix="ramify-test-store-"))
os.environ["RAMIFY_DATA_DIR"] = str(_TEMP_STORE)

if os.environ.get("RAMIFY_TEST_LIVE_MODEL") != "1":
    os.environ.setdefault("RAMIFY_DISABLE_AGENT", "1")


@atexit.register
def _cleanup() -> None:
    shutil.rmtree(_TEMP_STORE, ignore_errors=True)
