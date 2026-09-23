"""SQLite side of the kit: connections, core schema, range replace, sync_log, meta.

Rules kept from the single-project version:
- The write connection is in autocommit (isolation_level=None) and every chunk
  opens its own BEGIN IMMEDIATE. With Python's implicit transactions, any
  earlier small write (a meta value, a rejected field) left a transaction open
  and the chunk's BEGIN failed.
- A chunk replaces all of its days: DELETE by date range + INSERT inside one
  transaction. Rows have no id of their own, and a hash dedup would merge two
  genuine identical events fired in the same second.
- WAL journal, so queries keep working while a long sync writes; read-only
  commands open the file with mode=ro and cannot change it by accident.
- Source tables grow with their field lists: a field added to a source later
  becomes a new column in an existing database instead of a failed INSERT.
"""

from __future__ import annotations

import re
import sqlite3
import urllib.parse
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Iterator, Mapping

from . import GakError, flatten
from .sources.base import INTEGER, REAL, Table

SCHEMA_FILE = Path(__file__).with_name("schema_core.sql")
BATCH_ROWS = 5000
BUSY_TIMEOUT_SEC = 60
# Columns that tell this kit's static tables from same-named ones of other tools
# (the single-project exporter had sync_log / source_fields keyed by source only).
_SIGNATURE_COLUMNS = (("sync_log", "table_name"), ("source_fields", "table_name"),
                      ("event_params", "event_name"))


# --------------------------------------------------------------------------- #
# connections
# --------------------------------------------------------------------------- #

def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=BUSY_TIMEOUT_SEC, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def connect_readonly(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise GakError(f"database {path} does not exist yet; run `ga.py sync` first")
    uri = "file:{}?mode=ro".format(urllib.parse.quote(path.resolve().as_posix(), safe="/:"))
    conn = sqlite3.connect(uri, uri=True, timeout=BUSY_TIMEOUT_SEC)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[None]:
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        if conn.in_transaction:  # some errors (disk full) already rolled it back
            conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def quote(name: str) -> str:
    return '"{}"'.format(name.replace('"', '""'))


# --------------------------------------------------------------------------- #
# schema
# --------------------------------------------------------------------------- #

def ensure_schema(conn: sqlite3.Connection, tables: Iterable[Table]) -> None:
    """Create source tables from their definitions, then the static core schema."""
    for name, column in _SIGNATURE_COLUMNS:
        existing = table_columns(conn, name)
        if existing and column not in existing:
            raise GakError(f"{name} in this database has no {column} column: the file was made "
                           "by another tool; point [database].path or --db to a new file")
    json_tables = []
    for table in tables:
        _ensure_source_table(conn, table)
        if table.json_field:
            json_tables.append(table.name)
    if len(json_tables) > 1:
        # event_params rows are deleted by date together with their table's range.
        raise GakError(f"only one table may be flattened into event_params: {json_tables}")
    conn.executescript(SCHEMA_FILE.read_text(encoding="utf-8"))


def _ensure_source_table(conn: sqlite3.Connection, table: Table) -> None:
    columns = [("id", "INTEGER PRIMARY KEY"), ("date", "TEXT"), ("load_date", "TEXT")]
    columns += [(name, table.column_type(name)) for name in table.all_fields()]
    if table.json_field:
        columns.append((flatten.raw_column(table.json_field), "TEXT"))
    name = quote(table.name)
    conn.execute("CREATE TABLE IF NOT EXISTS {} (\n  {}\n)".format(
        name, ",\n  ".join(f"{quote(c)} {t}" for c, t in columns)))
    existing = set(table_columns(conn, table.name))
    for column, column_type in columns:
        if column not in existing:
            conn.execute(f"ALTER TABLE {name} ADD COLUMN {quote(column)} {column_type}")
    conn.execute(f"CREATE INDEX IF NOT EXISTS {quote('idx_' + table.name + '_date')} "
                 f"ON {name}(date)")
    fields = table.all_fields()
    if "appmetrica_device_id" in fields:
        conn.execute(f"CREATE INDEX IF NOT EXISTS {quote('idx_' + table.name + '_device')} "
                     f"ON {name}(appmetrica_device_id)")
    if "event_name" in fields:
        conn.execute(f"CREATE INDEX IF NOT EXISTS {quote('idx_' + table.name + '_name_date')} "
                     f"ON {name}(event_name, date)")


def list_tables(conn: sqlite3.Connection, kind: str = "table") -> list[str]:
    return [row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = ? AND name NOT LIKE 'sqlite_%' "
        "ORDER BY name", (kind,))]


def table_columns(conn: sqlite3.Connection, name: str) -> list[str]:
    return [row[1] for row in conn.execute(f"PRAGMA table_info({quote(name)})")]


# --------------------------------------------------------------------------- #
# range replace and sync_log
# --------------------------------------------------------------------------- #

@dataclass
class RangeResult:
    per_day: dict[str, int]  # stored rows per day
    outside: int             # rows dated outside the range, skipped


@dataclass(frozen=True)
class DayState:
    is_final: bool
    loaded_at: datetime | None


def replace_range(conn: sqlite3.Connection, table: Table, fields: list[str],
                  rows: Iterable[Mapping[str, str]], start: date, end: date,
                  load_date: str, flatten_params: bool = True) -> RangeResult:
    """Replace every day of [start, end] with `rows`; the caller holds the transaction.

    A row dated outside the range is skipped: the request for its own day
    delivers it, and storing it here would duplicate it on every reload of
    this range while its day, once final, is never cleaned again.
    Without `flatten_params` the range's old event_params rows are still
    deleted (their event ids die with the rows) but no new ones are written.
    """
    first, last = start.isoformat(), end.isoformat()
    columns = ["id", "date", "load_date", *fields]
    if table.json_field:
        columns.append(flatten.raw_column(table.json_field))
    insert_sql = "INSERT INTO {} ({}) VALUES ({})".format(
        quote(table.name), ", ".join(quote(c) for c in columns), ", ".join("?" * len(columns)))
    param_sql = ("INSERT INTO event_params (event_id, date, load_date, event_name, key, "
                 "value_text, value_num) VALUES (?, ?, ?, ?, ?, ?, ?)")

    next_id = conn.execute(f"SELECT COALESCE(MAX(id), 0) + 1 FROM {quote(table.name)}").fetchone()[0]
    conn.execute(f"DELETE FROM {quote(table.name)} WHERE date BETWEEN ? AND ?", (first, last))
    if table.json_field:
        conn.execute("DELETE FROM event_params WHERE date BETWEEN ? AND ?", (first, last))

    types = [table.column_type(name) for name in fields]
    json_index = fields.index(table.json_field) if table.json_field in fields else -1
    per_day: dict[str, int] = {}
    outside = 0
    batch: list[tuple] = []
    params_batch: list[tuple] = []
    for row in rows:
        day = (row.get(table.date_field) or "")[:10] or first
        if not first <= day <= last:
            outside += 1
            continue
        row_id = next_id
        next_id += 1
        per_day[day] = per_day.get(day, 0) + 1
        values: list[object] = [row_id, day, load_date]
        raw_json = None
        for index, name in enumerate(fields):
            value = row.get(name, "")
            if index == json_index:
                parsed = flatten.parse_json(value)
                values.append(parsed.normalized)
                raw_json = parsed.raw
                if parsed.params and flatten_params:
                    params_batch.extend(flatten.param_rows(
                        row_id, day, load_date, row.get(flatten.EVENT_NAME_FIELD) or None,
                        parsed.params))
            else:
                values.append(_coerce(types[index], value))
        if table.json_field:
            values.append(raw_json)
        batch.append(tuple(values))
        if len(batch) >= BATCH_ROWS:
            conn.executemany(insert_sql, batch)
            batch.clear()
        if len(params_batch) >= BATCH_ROWS:
            conn.executemany(param_sql, params_batch)
            params_batch.clear()
    if batch:
        conn.executemany(insert_sql, batch)
    if params_batch:
        conn.executemany(param_sql, params_batch)
    return RangeResult(per_day, outside)


def _coerce(column_type: str, value: str | None) -> object:
    if value is None or value == "":
        return None
    if column_type == INTEGER:
        try:
            return int(value)
        except ValueError:
            try:
                return int(float(value))
            except ValueError:
                return None
    if column_type == REAL:
        try:
            return float(value)
        except ValueError:
            return None
    return value


def mark_day(conn: sqlite3.Connection, source: str, table: str, day: date, rows: int,
             final: bool, loaded_at: datetime) -> None:
    conn.execute(
        "INSERT INTO sync_log (source, table_name, day, loaded_at, rows, is_final) "
        "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (source, table_name, day) DO UPDATE SET "
        "loaded_at = excluded.loaded_at, rows = excluded.rows, is_final = excluded.is_final",
        (source, table, day.isoformat(), loaded_at.isoformat(timespec="seconds"), rows,
         int(final)))


def day_states(conn: sqlite3.Connection, source: str, table: str) -> dict[str, DayState]:
    states = {}
    for row in conn.execute("SELECT day, is_final, loaded_at FROM sync_log "
                            "WHERE source = ? AND table_name = ?", (source, table)):
        try:
            loaded_at = datetime.fromisoformat(row["loaded_at"])
        except (TypeError, ValueError):
            loaded_at = None
        states[row["day"]] = DayState(bool(row["is_final"]), loaded_at)
    return states


def checkpoint(conn: sqlite3.Connection) -> None:
    """Fold the WAL into the database and truncate it.

    A chunk is one transaction, so the WAL holds a second copy of everything it
    wrote; left alone, a big backfill needs twice its size on disk.
    """
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()


def db_file(conn: sqlite3.Connection) -> Path | None:
    """The main database file of a connection (None for an in-memory one)."""
    for row in conn.execute("PRAGMA database_list"):
        if row[1] == "main" and row[2]:
            return Path(row[2])
    return None


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


# --------------------------------------------------------------------------- #
# meta and source fields
# --------------------------------------------------------------------------- #

def set_meta(conn: sqlite3.Connection, key: str, value: object) -> None:
    conn.execute("INSERT INTO meta (key, value) VALUES (?, ?) "
                 "ON CONFLICT (key) DO UPDATE SET value = excluded.value", (key, str(value)))


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def rejected_fields(conn: sqlite3.Connection, source: str, table: str) -> set[str]:
    row = conn.execute("SELECT rejected FROM source_fields WHERE source = ? AND table_name = ?",
                       (source, table)).fetchone()
    return {name for name in ((row[0] if row else "") or "").split(",") if name}


def store_fields(conn: sqlite3.Connection, source: str, table: str, accepted: Iterable[str],
                 rejected: Iterable[str] = ()) -> None:
    """Remember the working field list; rejected names accumulate across runs."""
    known = rejected_fields(conn, source, table) | set(rejected)
    conn.execute(
        "INSERT INTO source_fields (source, table_name, accepted, rejected, updated_at) "
        "VALUES (?, ?, ?, ?, ?) ON CONFLICT (source, table_name) DO UPDATE SET "
        "accepted = excluded.accepted, rejected = excluded.rejected, "
        "updated_at = excluded.updated_at",
        (source, table, ",".join(accepted), ",".join(sorted(known)), now_iso()))


# --------------------------------------------------------------------------- #
# project SQL files (model/)
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Statement:
    line: int   # 1-based line where the statement starts
    sql: str


def split_statements(sql: str) -> list[Statement]:
    """Split a script into statements the way SQLite sees them.

    sqlite3.complete_statement understands string literals, comments and
    CREATE TRIGGER ... END blocks, so a ';' inside any of them does not split.
    """
    statements: list[Statement] = []
    buffer: list[str] = []
    start = 1
    for number, line in enumerate(sql.splitlines(keepends=True), start=1):
        if not buffer:
            if not line.strip() or line.lstrip().startswith("--"):
                continue  # comments between statements: the reported line is the SQL's own
            start = number
        buffer.append(line)
        text = "".join(buffer)
        if sqlite3.complete_statement(text):
            statements.append(Statement(start, text.strip()))
            buffer = []
    tail = "".join(buffer).strip()
    if tail:
        statements.append(Statement(start, tail))  # no final ';' - SQLite judges it
    return statements


_TRANSACTION_WORDS = ("BEGIN", "COMMIT", "END", "ROLLBACK", "SAVEPOINT", "RELEASE")
_CREATE_VIEW_RE = re.compile(
    r'CREATE\s+(?:TEMP\s+|TEMPORARY\s+)?VIEW\s+(?:IF\s+NOT\s+EXISTS\s+)?'
    r'("(?:[^"]|"")+"|\[[^\]]+\]|`[^`]+`|[\w.]+)', re.IGNORECASE)


def _created_view(sql: str) -> str | None:
    match = _CREATE_VIEW_RE.match(sql)
    return match.group(1) if match else None


def apply_sql_files(conn: sqlite3.Connection, files: list[Path]) -> int:
    """Run every statement of `files` in one transaction; all or nothing.

    On failure raises GakError naming the file, the line and the start of the
    statement, and the database is left exactly as before.
    """
    plan = []
    for path in files:
        for statement in split_statements(path.read_text(encoding="utf-8-sig")):
            first_word = statement.sql.lstrip("(").split(None, 1)[0].upper().rstrip(";")
            if first_word in _TRANSACTION_WORDS:
                raise GakError(f"{path.name} line {statement.line}: remove {first_word}; "
                               "model apply already runs all files in one transaction")
            plan.append((path, statement))
    with transaction(conn):
        for path, statement in plan:
            try:
                conn.execute(statement.sql)
                view = _created_view(statement.sql)
                if view:
                    # SQLite accepts a view over a missing table or column and fails
                    # only when it is queried; compiling it here reports the file.
                    conn.execute(f"EXPLAIN SELECT * FROM {view}").fetchall()
            except sqlite3.Error as error:
                start = " ".join(statement.sql.split())[:80]
                raise GakError(f"{path.name} line {statement.line}: {error} "
                               f"(statement starts: {start})") from None
    return len(plan)
