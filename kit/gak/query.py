"""Named and ad-hoc SQL: find a query, bind :params, render the rows.

Queries are plain .sql files whose first line is `-- <title>`. The project's
analytics/queries/ comes first, the kit's generic ones (kit/gak/queries/) second,
so a project may override a kit query by name. :since, :until and :limit have
defaults so every query runs bare; --param adds or overrides values, and a
parameter the statement does not mention is simply ignored. Output is plain
text an agent can read: the table format is capped (200 rows by default) and
says so; csv/json/md print everything unless --limit.
"""

from __future__ import annotations

import csv
import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence, TextIO

from . import GakError

KIT_QUERIES = Path(__file__).with_name("queries")
PROJECT_QUERIES = "queries"
DEFAULT_PARAMS: dict[str, Any] = {"since": "0000-01-01", "until": "9999-12-31", "limit": 200}
TABLE_ROW_CAP = 200
CELL_WIDTH = 42
FORMATS = ("table", "md", "csv", "json")

_INT_RE = re.compile(r"[+-]?\d+")
_FLOAT_RE = re.compile(r"[+-]?(\d+\.\d*|\.\d+|\d+)([eE][+-]?\d+)?")


@dataclass(frozen=True)
class NamedQuery:
    name: str
    path: Path
    origin: str      # "project" or "kit"
    title: str
    overrides: bool  # a project query hiding a kit query of the same name


@dataclass
class Result:
    columns: list[str]
    rows: list[Sequence[Any]]
    truncated: bool = False


# --------------------------------------------------------------------------- #
# finding queries
# --------------------------------------------------------------------------- #

def title_of(path: Path) -> str:
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        stripped = line.strip()
        if stripped.startswith("--"):
            return stripped.lstrip("-").strip()
        if stripped:
            break
    return ""


def list_queries(analytics_dir: Path) -> list[NamedQuery]:
    project = {p.stem: p for p in sorted((analytics_dir / PROJECT_QUERIES).glob("*.sql"))}
    kit = {p.stem: p for p in sorted(KIT_QUERIES.glob("*.sql"))}
    found = [NamedQuery(name, path, "project", title_of(path), name in kit)
             for name, path in project.items()]
    found += [NamedQuery(name, path, "kit", title_of(path), False)
              for name, path in kit.items() if name not in project]
    return found


def resolve(analytics_dir: Path, name_or_path: str) -> Path:
    """A query name (project first, then kit) or a path to a .sql file."""
    if name_or_path.endswith(".sql") or "/" in name_or_path or "\\" in name_or_path:
        for candidate in (Path(name_or_path), analytics_dir / name_or_path):
            if candidate.is_file():
                return candidate
        raise GakError(f"query file {name_or_path} not found")
    for folder in (analytics_dir / PROJECT_QUERIES, KIT_QUERIES):
        candidate = folder / f"{name_or_path}.sql"
        if candidate.is_file():
            return candidate
    raise GakError(f"unknown query '{name_or_path}'; `ga.py query list` shows the available ones")


# --------------------------------------------------------------------------- #
# running
# --------------------------------------------------------------------------- #

def parse_params(pairs: Sequence[str]) -> dict[str, Any]:
    """--param k=v values; numbers become numbers so comparisons work as expected."""
    params: dict[str, Any] = {}
    for pair in pairs:
        if "=" not in pair:
            raise GakError(f"--param expects NAME=VALUE, got '{pair}'")
        name, value = (part.strip() for part in pair.split("=", 1))
        if _INT_RE.fullmatch(value):
            params[name] = int(value)
        elif _FLOAT_RE.fullmatch(value):
            params[name] = float(value)
        else:
            params[name] = value
    return params


def bind_params(overrides: dict[str, Any]) -> dict[str, Any]:
    """Defaults plus overrides; sqlite ignores names the statement does not use."""
    return {**DEFAULT_PARAMS, **overrides}


def execute(conn: sqlite3.Connection, sql: str, params: dict[str, Any],
            limit: int | None = None) -> Result:
    try:
        cursor = conn.execute(sql, params)
    except sqlite3.ProgrammingError as error:
        text = str(error)
        match = re.search(r"binding parameter :(\w+)", text)
        if match:
            raise GakError(f"the query needs :{match.group(1)}; pass "
                           f"--param {match.group(1)}=VALUE") from None
        if "one statement at a time" in text:
            raise GakError("only one SQL statement per query; put setup into model/ "
                           "and run `ga.py model apply`") from None
        raise GakError(f"SQL error: {text}") from None
    except sqlite3.Error as error:
        raise GakError(f"SQL error: {error}") from None
    if cursor.description is None:
        return Result([], [])
    columns = [d[0] for d in cursor.description]
    if limit is None:
        return Result(columns, cursor.fetchall())
    rows = cursor.fetchmany(limit + 1)
    return Result(columns, rows[:limit], truncated=len(rows) > limit)


def run_named(conn: sqlite3.Connection, path: Path, overrides: dict[str, Any],
              limit: int | None = None) -> Result:
    sql = path.read_text(encoding="utf-8-sig")
    return execute(conn, sql, bind_params(overrides), limit)


# --------------------------------------------------------------------------- #
# rendering
# --------------------------------------------------------------------------- #

def display_limit(fmt: str, limit: int | None) -> int | None:
    """Rows to fetch: --limit wins; the table format is capped by default."""
    if limit is not None:
        return max(0, limit)
    return TABLE_ROW_CAP if fmt == "table" else None


def render(result: Result, fmt: str, out: TextIO) -> None:
    if not result.columns:
        out.write("statement returned no rows\n")
        return
    if fmt == "csv":
        writer = csv.writer(out, lineterminator="\n")
        writer.writerow(result.columns)
        writer.writerows(result.rows)
    elif fmt == "json":
        records = [dict(zip(result.columns, row)) for row in result.rows]
        out.write(json.dumps(records, ensure_ascii=False, indent=1, default=str) + "\n")
    elif fmt == "md":
        _render_markdown(result, out)
    else:
        _render_table(result, out)
    if result.truncated and fmt in ("table", "md"):
        out.write(f"(showing the first {len(result.rows)} rows; more exist - use --limit N "
                  "or --format csv)\n")


def _render_table(result: Result, out: TextIO) -> None:
    cells = [[_cell(value, CELL_WIDTH) for value in row] for row in result.rows]
    numeric = [bool(result.rows) and all(isinstance(row[i], (int, float)) or row[i] is None
                                         for row in result.rows)
               for i in range(len(result.columns))]
    widths = [len(name) for name in result.columns]
    for row in cells:
        for i, value in enumerate(row):
            widths[i] = max(widths[i], len(value))

    def line(values: Sequence[str]) -> str:
        parts = [v.rjust(widths[i]) if numeric[i] else v.ljust(widths[i])
                 for i, v in enumerate(values)]
        return "  ".join(parts).rstrip()

    out.write(line(result.columns) + "\n")
    out.write("  ".join("-" * w for w in widths) + "\n")
    for row in cells:
        out.write(line(row) + "\n")
    out.write(f"{len(cells)} row{'s' if len(cells) != 1 else ''}\n")


def _render_markdown(result: Result, out: TextIO) -> None:
    out.write("| " + " | ".join(result.columns) + " |\n")
    out.write("|" + "|".join("---" for _ in result.columns) + "|\n")
    for row in result.rows:
        out.write("| " + " | ".join(_cell(v).replace("|", "\\|") for v in row) + " |\n")


def _cell(value: Any, width: int | None = None) -> str:
    if value is None:
        text = ""
    elif isinstance(value, float):
        text = format(value, ".12g")
    elif isinstance(value, bytes):
        text = f"<{len(value)} bytes>"
    else:
        text = " ".join(str(value).split()) if isinstance(value, str) else str(value)
    if width and len(text) > width:
        return text[:width - 1] + "~"
    return text
