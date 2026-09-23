#!/usr/bin/env python3
"""Entry point of game-analytics-kit inside this project.

Run every command from the project root:
    py analytics/ga.py status          (Windows)
    python3 analytics/ga.py status     (macOS / Linux)

The engine lives in analytics/kit/ and is managed by the kit's install.py;
edit project files (analytics.toml, model/, queries/, notes/), not the kit.
"""

import sys
from pathlib import Path

ANALYTICS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ANALYTICS_DIR / "kit"))

from gak.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:], analytics_dir=ANALYTICS_DIR))
