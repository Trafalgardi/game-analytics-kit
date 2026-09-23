"""game-analytics-kit engine ("gak").

Pulls a game's raw analytics into a local SQLite database, models it per
project and runs queries; every command is reached through `analytics/ga.py`.
Standard library only, so the kit runs on any machine with Python 3.11+.
"""

__version__ = "0.3.0"


class GakError(Exception):
    """An expected failure the user can act on.

    The CLI prints the message as one line on stderr and exits non-zero, so
    the text must say what went wrong and what to do next - never a traceback.
    """
