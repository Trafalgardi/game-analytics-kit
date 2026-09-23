"""analytics.toml and secrets.

The config is committed with the project; secrets never are. A token is looked
up in this order: environment variable -> analytics/.env ->
~/.config/game-analytics-kit/.env (one token serves every project of the same
account). The token value is never printed or logged: callers only learn which
of those places it came from, and nothing here writes it anywhere.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from . import GakError

CONFIG_FILE = "analytics.toml"
ENV_FILE = ".env"
USER_ENV_FILE = Path("~/.config/game-analytics-kit/.env")
DEFAULT_DB = "data/analytics.db"
DEFAULT_SOURCE = "appmetrica"  # the only source in v0.1; used when the toml names none

SOURCE_DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "api_key": "",
    "app_id": "",
    "since": "",
    "tables": None,          # None = the source's default set; "all" or a list
    "chunk_days": 7,
    "fresh_days": 7,
    "refresh_after_hours": 12,
    "sample": 1.0,           # share of devices kept, 0 < r <= 1 (deterministic by device id)
    "flatten_params": True,  # write event_params; ~70% of the database for a game with many params
}


@dataclass
class Config:
    analytics_dir: Path
    path: Path
    exists: bool
    project: dict[str, Any] = field(default_factory=dict)
    database: dict[str, Any] = field(default_factory=dict)
    sources: dict[str, dict[str, Any]] = field(default_factory=dict)
    filters: dict[str, Any] = field(default_factory=dict)

    @property
    def db_path(self) -> Path:
        return self.resolve(str(self.database.get("path") or DEFAULT_DB))

    @property
    def project_name(self) -> str:
        return str(self.project.get("name") or "")

    @property
    def report_language(self) -> str:
        return str(self.project.get("report_language") or "en")

    def resolve(self, relative: str | Path) -> Path:
        """Paths in the config and on the command line are relative to analytics/."""
        path = Path(relative).expanduser()
        return path if path.is_absolute() else self.analytics_dir / path

    def source(self, name: str) -> dict[str, Any]:
        return dict(SOURCE_DEFAULTS, **self.sources.get(name, {}))


def load(analytics_dir: Path) -> Config:
    path = analytics_dir / CONFIG_FILE
    if not path.exists():
        return Config(analytics_dir, path, False, sources={DEFAULT_SOURCE: {}})
    import tomllib  # here, so Python < 3.11 still reaches the CLI's version message

    try:
        data = tomllib.loads(path.read_text(encoding="utf-8-sig"))
    except tomllib.TOMLDecodeError as error:
        raise GakError(f"{path}: {error}") from None
    sources = data.get("sources") or {DEFAULT_SOURCE: {}}
    for name, options in sources.items():
        _validate_source(name, options)
    return Config(analytics_dir, path, True,
                  project=data.get("project") or {},
                  database=data.get("database") or {},
                  sources=sources,
                  filters=data.get("filters") or {})


def _validate_source(name: str, options: Any) -> None:
    where = f"{CONFIG_FILE} [sources.{name}]"
    if not isinstance(options, dict):
        raise GakError(f"{where} must be a table")
    for key in ("since", "api_key", "app_id"):  # TOML may hand over a date or an integer
        options[key] = str(options.get(key) or "").strip()
    if options["since"]:
        parse_date(options["since"], f"{where} since")
    tables = options.get("tables")
    if tables is not None and tables != "all" and not (
            isinstance(tables, list) and all(isinstance(t, str) for t in tables)):
        raise GakError(f'{where} tables must be a list of names or "all"')
    for key, minimum in (("chunk_days", 1), ("fresh_days", 0), ("refresh_after_hours", 0)):
        value = options.get(key, SOURCE_DEFAULTS[key])
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value < minimum:
            raise GakError(f"{where} {key} must be a number >= {minimum}")
    sample = options.get("sample", 1.0)
    if isinstance(sample, bool) or not isinstance(sample, (int, float)) or not 0 < sample <= 1:
        raise GakError(f"{where} sample must be a number with 0 < sample <= 1, e.g. 0.1")
    if not isinstance(options.get("flatten_params", True), bool):
        raise GakError(f"{where} flatten_params must be true or false")


def parse_date(text: str, what: str = "date") -> date:
    try:
        return datetime.strptime(text.strip(), "%Y-%m-%d").date()
    except ValueError:
        raise GakError(f"{what} must be YYYY-MM-DD, got '{text}'") from None


def read_env_file(path: Path) -> dict[str, str]:
    """KEY=VALUE lines; comments, blank lines, `export ` and quotes tolerated."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def find_token(analytics_dir: Path, name: str) -> tuple[str | None, str]:
    """(token, where it came from) or (None, "") - the value itself is never shown."""
    value = os.environ.get(name, "").strip()
    if value:
        return value, f"environment variable {name}"
    for path, label in ((analytics_dir / ENV_FILE, "analytics/.env"),
                        (USER_ENV_FILE.expanduser(), "~/.config/game-analytics-kit/.env")):
        value = read_env_file(path).get(name, "").strip()
        if value:
            return value, label
    return None, ""
