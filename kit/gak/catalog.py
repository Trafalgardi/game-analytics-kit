"""Event catalog and the v_events scaffold.

The catalog answers "what does the game actually send": every event name with
every parameter key, how often, on how many devices, how varied, how numeric,
with sample values. It is the first thing to read before modelling, because
the client code and the spec drift from what arrives.

The scaffold turns the catalog into model/010_v_events.sql: a v_events view
with one typed column per frequent parameter key. It is a starting point the
agent edits (rename, retype, drop noise, add derived columns); after that the
file belongs to the project and is never overwritten without --force.

Both read event_params when sync filled it. A big game syncs with
flatten_params = false (event_params would be most of the database); then the
parameters of the latest events (200k by default, within --since) are
flattened on the fly with json_each into a temp table of the same shape, and
the output says it sampled.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date

from . import GakError, flatten

EVENTS_TABLE = "events"
DEVICE_COLUMN = "appmetrica_device_id"
JSON_COLUMN = "event_json"
NUMERIC_SHARE_FOR_NUMBER = 0.95
MAX_EVENTS = 200_000  # events read from event_json when event_params is not filled

# (column in v_events, expression over events e)
BASE_COLUMNS: list[tuple[str, str]] = [
    ("id", "e.id"),
    ("date", "e.date"),
    ("event_datetime", "e.event_datetime"),
    ("event_timestamp", "e.event_timestamp"),
    ("event_name", "e.event_name"),
    ("device_id", f"e.{DEVICE_COLUMN}"),
    ("session_id", "e.session_id"),
    ("app_version_name", "e.app_version_name"),
    ("app_build_number", "e.app_build_number"),
    ("os_version", "e.os_version"),
    ("device_model", "e.device_model"),
    ("country_iso_code", "e.country_iso_code"),
]


# --------------------------------------------------------------------------- #
# catalog
# --------------------------------------------------------------------------- #

@dataclass
class CatalogRow:
    event_name: str
    events: int
    key: str | None
    occurrences: int
    devices: int
    distinct_values: int
    numeric_share: float | None
    samples: list[str] = field(default_factory=list)

    @property
    def share(self) -> float:
        return self.occurrences / self.events if self.events else 0.0


CATALOG_COLUMNS = ["event_name", "events", "key", "occurrences", "share_pct", "devices",
                   "distinct_values", "numeric_share", "samples"]


def require_events(conn: sqlite3.Connection) -> None:
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if EVENTS_TABLE not in tables or "event_params" not in tables:
        raise GakError("no events table in this database; run `ga.py sync` first")
    if conn.execute(f"SELECT 1 FROM {EVENTS_TABLE} LIMIT 1").fetchone() is None:
        raise GakError("the events table is empty; run `ga.py sync` first")


@dataclass(frozen=True)
class ParamSource:
    """Where parameters are read from: event_params, or a sample flattened on the fly."""

    events: str  # table with id, date, event_name and the device column
    params: str  # table shaped like event_params
    note: str    # empty, or what was sampled and why


def param_source(conn: sqlite3.Connection, since: date | None,
                 max_events: int = MAX_EVENTS) -> ParamSource:
    require_events(conn)
    bound = _bound(since)
    if _flattened(conn, bound):
        return ParamSource(EVENTS_TABLE, "event_params", "")
    conn.create_function("gak_number", 1, flatten.as_number, deterministic=True)
    conn.execute("DROP TABLE IF EXISTS temp.gak_params")
    conn.execute("DROP TABLE IF EXISTS temp.gak_events")
    conn.execute(f"""
        CREATE TEMP TABLE gak_events AS
        SELECT id, date, event_name, {DEVICE_COLUMN}, {JSON_COLUMN} FROM {EVENTS_TABLE}
        WHERE date >= ? ORDER BY date DESC, id DESC LIMIT ?""", (bound, max_events))
    # The same values flatten.param_rows writes at load time.
    conn.execute(f"""
        CREATE TEMP TABLE gak_params AS
        SELECT e.id AS event_id, e.date, e.event_name, j.key AS key,
               CASE j.type WHEN 'null' THEN NULL WHEN 'true' THEN 'true'
                           WHEN 'false' THEN 'false' ELSE CAST(j.value AS TEXT) END AS value_text,
               CASE j.type WHEN 'integer' THEN j.value WHEN 'real' THEN j.value
                           WHEN 'true' THEN 1.0 WHEN 'false' THEN 0.0
                           WHEN 'text' THEN gak_number(j.value) END AS value_num
        FROM temp.gak_events e, json_each(e.{JSON_COLUMN}) j
        WHERE json_type(e.{JSON_COLUMN}) = 'object'""")
    sampled = conn.execute("SELECT COUNT(*) FROM temp.gak_events").fetchone()[0]
    total = conn.execute(f"SELECT COUNT(*) FROM {EVENTS_TABLE} WHERE date >= ?",
                         (bound,)).fetchone()[0]
    if sampled == total:
        scope = f"all {total:,} events"
    else:
        scope = f"a sample: the latest {sampled:,} of {total:,} events (--max-events, --since)"
    return ParamSource("temp.gak_events", "temp.gak_params",
                       "event_params is not filled (flatten_params = false); parameters "
                       f"were read from event_json of {scope}")


def _flattened(conn: sqlite3.Connection, bound: str) -> bool:
    off = conn.execute("SELECT 1 FROM meta WHERE key LIKE '%.flatten_params' AND value = '0' "
                       "LIMIT 1").fetchone()
    if off:  # rows left by an earlier flattened sync would give a partial picture
        return False
    return conn.execute("SELECT 1 FROM event_params WHERE date >= ? LIMIT 1",
                        (bound,)).fetchone() is not None


def _bound(since: date | None) -> str:
    return since.isoformat() if since else "0000-01-01"


def catalog(conn: sqlite3.Connection, since: date | None = None, min_count: int = 1,
            max_events: int = MAX_EVENTS) -> tuple[list[CatalogRow], str]:
    """Event x key rows, most frequent events first (events without params get key
    None), and a note that is non-empty when the parameters were sampled."""
    src = param_source(conn, since, max_events)
    params = {"since": _bound(since), "min_count": min_count}
    rows = conn.execute(f"""
        WITH ev AS (
            SELECT event_name, COUNT(*) AS events, COUNT(DISTINCT {DEVICE_COLUMN}) AS devices
            FROM {src.events} WHERE date >= :since GROUP BY event_name
        ),
        kp AS (
            SELECT p.event_name, p.key,
                   COUNT(*) AS occurrences,
                   COUNT(DISTINCT e.{DEVICE_COLUMN}) AS devices,
                   COUNT(DISTINCT p.value_text) AS distinct_values,
                   1.0 * SUM(p.value_num IS NOT NULL)
                       / NULLIF(SUM(p.value_text IS NOT NULL), 0) AS numeric_share
            FROM {src.params} p JOIN {src.events} e ON e.id = p.event_id
            WHERE p.date >= :since
            GROUP BY p.event_name, p.key
        )
        SELECT ev.event_name, ev.events, kp.key,
               COALESCE(kp.occurrences, ev.events) AS occurrences,
               COALESCE(kp.devices, ev.devices) AS devices,
               COALESCE(kp.distinct_values, 0) AS distinct_values,
               kp.numeric_share
        FROM ev
        LEFT JOIN kp ON kp.event_name IS ev.event_name
        WHERE COALESCE(kp.occurrences, ev.events) >= :min_count
        ORDER BY ev.events DESC, ev.event_name, kp.occurrences DESC, kp.key
    """, params).fetchall()
    samples = _samples(conn, src.params, params["since"])
    return [CatalogRow(r[0] or "", r[1], r[2], r[3], r[4], r[5], r[6],
                       samples.get((r[0], r[2]), [])) for r in rows], src.note


def _samples(conn: sqlite3.Connection, table: str, since: str,
             per_key: int = 3) -> dict[tuple, list[str]]:
    """The most frequent values of every (event, key)."""
    result: dict[tuple, list[str]] = {}
    for row in conn.execute(f"""
        WITH counted AS (
            SELECT event_name, key, value_text, COUNT(*) AS n
            FROM {table} WHERE date >= ? AND value_text IS NOT NULL
            GROUP BY event_name, key, value_text
        ),
        ranked AS (
            SELECT *, ROW_NUMBER() OVER (PARTITION BY event_name, key
                                         ORDER BY n DESC, value_text) AS rn
            FROM counted
        )
        SELECT event_name, key, value_text FROM ranked WHERE rn <= ? ORDER BY rn
    """, (since, per_key)):
        result.setdefault((row[0], row[1]), []).append(row[2])
    return result


def catalog_table(rows: list[CatalogRow]) -> list[tuple]:
    """Rows shaped like CATALOG_COLUMNS for query.render."""
    return [(r.event_name, r.events, r.key or "", r.occurrences,
             round(100.0 * r.share, 1) if r.key else None, r.devices,
             r.distinct_values if r.key else None,
             round(r.numeric_share, 3) if r.numeric_share is not None else None,
             " | ".join(_clip(s) for s in r.samples)) for r in rows]


def _clip(text: str, width: int = 40) -> str:
    text = " ".join(text.split())
    return text if len(text) <= width else text[:width - 1] + "~"


# --------------------------------------------------------------------------- #
# v_events scaffold
# --------------------------------------------------------------------------- #

@dataclass
class KeyStats:
    key: str
    occurrences: int = 0
    values: int = 0          # non-null values
    numeric: int = 0
    integers: int = 0
    decimal_commas: int = 0  # numeric values written with a comma ("1,5")
    max_share: float = 0.0   # highest share of one event's rows carrying the key
    events: list[tuple[str, int, int]] = field(default_factory=list)  # (event, n, event total)

    @property
    def sql_type(self) -> str:
        if self.values and self.numeric / self.values >= NUMERIC_SHARE_FOR_NUMBER:
            return "INTEGER" if self.integers == self.numeric else "REAL"
        return "TEXT"

    @property
    def primary_event(self) -> str:
        return max(self.events, key=lambda e: (e[1], e[0]))[0]


@dataclass
class Scaffold:
    sql: str
    keys: int         # keys seen
    columns: int      # parameter columns written
    events: int       # events the stats cover
    note: str = ""    # non-empty when the parameters were sampled from event_json


def key_stats(conn: sqlite3.Connection, since: date | None = None,
              max_events: int = MAX_EVENTS) -> tuple[list[KeyStats], int, str]:
    """Per-key statistics, the number of events they cover, and the sampling note."""
    src = param_source(conn, since, max_events)
    bound = _bound(since)
    stats: dict[str, KeyStats] = {}
    for row in conn.execute(f"""
        WITH ev AS (
            SELECT event_name, COUNT(*) AS n FROM {src.events}
            WHERE date >= :since GROUP BY event_name
        )
        SELECT p.event_name, p.key, COUNT(*) AS n,
               SUM(p.value_text IS NOT NULL) AS vals,
               SUM(p.value_num IS NOT NULL) AS nums,
               SUM(p.value_num IS NOT NULL AND p.value_num = CAST(p.value_num AS INTEGER)) AS ints,
               SUM(p.value_num IS NOT NULL AND instr(p.value_text, ',') > 0) AS commas,
               ev.n AS total
        FROM {src.params} p JOIN ev ON ev.event_name IS p.event_name
        WHERE p.date >= :since
        GROUP BY p.event_name, p.key
    """, {"since": bound}):
        item = stats.setdefault(row["key"], KeyStats(row["key"]))
        item.occurrences += row["n"]
        item.values += row["vals"]
        item.numeric += row["nums"]
        item.integers += row["ints"]
        item.decimal_commas += row["commas"]
        item.max_share = max(item.max_share, row["n"] / row["total"] if row["total"] else 0.0)
        item.events.append((row["event_name"] or "", row["n"], row["total"]))
    total = conn.execute(f"SELECT COUNT(*) FROM {src.events} WHERE date >= ?",
                         (bound,)).fetchone()[0]
    return list(stats.values()), total, src.note


def choose_keys(stats: list[KeyStats], min_share: float, top: int) -> list[KeyStats]:
    """Keys present in >= min_share of some event's rows, plus the `top` most frequent."""
    by_count = sorted(stats, key=lambda s: (-s.occurrences, s.key))
    chosen = {s.key for s in stats if s.max_share >= min_share}
    chosen.update(s.key for s in by_count[:max(0, top)])
    return [s for s in by_count if s.key in chosen]


def scaffold(conn: sqlite3.Connection, *, since: date | None, min_share: float, top: int,
             generated_on: date, max_events: int = MAX_EVENTS) -> Scaffold:
    stats, total, note = key_stats(conn, since, max_events)
    body, skipped, written = _columns(choose_keys(stats, min_share, top))
    header = _header(total, since, min_share, top, generated_on)
    if note:
        header.insert(-1, f"-- Parameters: {note}.")
    if skipped:
        header.insert(-1, f"-- Skipped keys with quotes or control characters: {skipped!r}")
    lines = header + ["DROP VIEW IF EXISTS v_events;", "CREATE VIEW v_events AS", "SELECT",
                      *body, f"FROM {EVENTS_TABLE} e;", ""]
    return Scaffold("\n".join(lines), len(stats), written, total, note)


_UNSAFE_KEY_CHARS = "\"\\\n\r\t"


def _columns(chosen: list[KeyStats]) -> tuple[list[str], list[str], int]:
    """SELECT list lines, keys that could not be written, parameter columns written."""
    lines = [f"    {expr} AS {name}," for name, expr in BASE_COLUMNS]
    taken = {name.lower() for name, _ in BASE_COLUMNS} | {JSON_COLUMN}
    skipped: list[str] = []
    written = 0
    for event, keys in _group_by_event(chosen):
        lines.append(f"    -- {event} ({_event_total(keys[0], event):,} events)")
        for item in keys:
            if not item.key or any(ch in item.key for ch in _UNSAFE_KEY_CHARS):
                skipped.append(item.key)
                continue
            notes = []
            others = [e for e, _, _ in sorted(item.events, key=lambda e: -e[1]) if e != event]
            if others:
                more = f" +{len(others) - 3}" if len(others) > 3 else ""
                notes.append(f"also in {', '.join(others[:3])}{more}")
            if item.sql_type != "TEXT" and item.numeric < item.values:
                # CAST turns the few non-numeric values into 0; say so where it is decided.
                notes.append(f"{item.numeric / item.values:.1%} numeric, the rest casts to 0")
            note = f"  -- {'; '.join(notes)}" if notes else ""
            lines.append(f"    {_extract(item)} AS {_alias(item.key, taken)},{note}")
            written += 1
    lines.append(f"    e.{JSON_COLUMN}")
    return lines, skipped, written


def _header(total: int, since: date | None, min_share: float, top: int,
            generated_on: date) -> list[str]:
    window = f"since {since}" if since else "all loaded days"
    rule = f"present in >= {min_share:.0%} of some event's rows (--min-share)"
    if top:
        rule += f", or among the {top} most frequent keys (--top)"
    return [
        "-- v_events: one row per event, game parameters as typed columns.",
        f"-- Generated by `ga.py model scaffold` on {generated_on} from {total:,} events ({window}).",
        f"-- A parameter key became a column when it is {rule}.",
        f"-- Types come from observed values: INTEGER/REAL when >= {NUMERIC_SHARE_FOR_NUMBER:.0%} "
        "of values are numeric, TEXT otherwise.",
        "-- This file belongs to the project now: rename columns, fix types, drop noise, add",
        "-- derived columns, keep it in git. `ga.py model apply` runs model/*.sql in name order.",
        "",
    ]


def _group_by_event(chosen: list[KeyStats]) -> list[tuple[str, list[KeyStats]]]:
    """Keys grouped under the event that sends them most, busiest events first."""
    groups: dict[str, list[KeyStats]] = {}
    for item in chosen:
        groups.setdefault(item.primary_event, []).append(item)
    return sorted(groups.items(), key=lambda g: (-_event_total(g[1][0], g[0]), g[0]))


def _event_total(item: KeyStats, event: str) -> int:
    return next((total for name, _, total in item.events if name == event), 0)


def _alias(key: str, taken: set[str]) -> str:
    """A quoted, unique (case-insensitively) column name for a parameter key."""
    name = key if key.lower() not in taken else f"p_{key}"
    candidate, suffix = name, 2
    while candidate.lower() in taken:
        candidate, suffix = f"{name}_{suffix}", suffix + 1
    taken.add(candidate.lower())
    return '"{}"'.format(candidate)


def _extract(item: KeyStats) -> str:
    path = "'$.\"{}\"'".format(item.key.replace("'", "''"))
    expr = f"json_extract(e.{JSON_COLUMN}, {path})"
    kind = item.sql_type
    if kind == "TEXT":
        return expr
    if kind == "REAL" and item.decimal_commas:
        # Some values arrive as "1,5" (a client on a comma-decimal locale).
        return f"CAST(REPLACE({expr}, ',', '.') AS REAL)"
    return f"CAST({expr} AS {kind})"
