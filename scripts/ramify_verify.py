"""Source-tree wrapper for the installed ``ramify-verify`` command.

Usage from the project root::

    python scripts/ramify_verify.py receipt.json
    python scripts/ramify_verify.py < receipt.json
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from ramify.cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
