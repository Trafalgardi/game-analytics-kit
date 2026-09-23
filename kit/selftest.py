#!/usr/bin/env python3
"""Offline selftest of game-analytics-kit: synthetic data, no token, no network.

Drives the real code paths inside a temporary folder that is removed at the
end: schema creation, the sync planner and range replace through a fake
Source, field drift, event_params flattening, catalog, model scaffold and
apply, every generic query, CSV import of messy console exports, the HTTP
client against a fake opener (202 polling, 429 Retry-After, retries, gzip),
the AppMetrica source against a fake HTTP layer, the CLI itself, and the
standard tables (keymetrics, dropoff) against a reference computed from the raw rows.

    py kit/selftest.py            from the kit repository
    py analytics/ga.py selftest   inside a project
"""

from __future__ import annotations

import contextlib
import csv
import dataclasses
import gzip
import io
import json
import random
import shutil
import sqlite3
import os
import sys
import tempfile
import time
import traceback
from datetime import date, datetime, timedelta
from email.message import Message
from pathlib import Path
from typing import Callable

KIT_DIR = Path(__file__).resolve().parent
if str(KIT_DIR) not in sys.path:
    sys.path.insert(0, str(KIT_DIR))

from gak import GakError, catalog, cli, csv_import, flatten, query, store, sync  # noqa: E402
from gak.http import Http, HttpError, parse_retry_after  # noqa: E402
from gak.sources import schema_tables  # noqa: E402
from gak.sources.appmetrica import AppMetricaSource  # noqa: E402
from gak.sources.appmetrica_fields import TABLES  # noqa: E402
from gak.sources.base import RequestRejected, Source, SourceError, Table  # noqa: E402

TODAY = date(2026, 9, 21)
NOW = datetime(2026, 9, 21, 12, 0, 0)
DAYS = 12
START = TODAY - timedelta(days=DAYS - 1)
FRESH_DAYS = 7
FRESH_EDGE = TODAY - timedelta(days=FRESH_DAYS)
DEVICES = 30
MODES = ["arena", "race", "survival"]
CONFIG = """[project]
name = "Selftest"
report_language = "en"

[database]
path = "data/analytics.db"

[sources.appmetrica]
api_key = "selftest-key"
"""


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def quiet(_message: str) -> None:
    pass


# --------------------------------------------------------------------------- #
# synthetic Logs API rows
# --------------------------------------------------------------------------- #

def device_id(index: int) -> str:
    return str(18_000_000_000_000_000_000 + index * 7919)  # above 2^63: must stay TEXT


def stamp(moment: datetime) -> dict[str, str]:
    return {"text": moment.strftime("%Y-%m-%d %H:%M:%S"), "ts": str(int(moment.timestamp()))}


def base_row(index: int, moment: datetime) -> dict[str, str]:
    return {
        "appmetrica_device_id": device_id(index),
        "installation_id": f"install-{index}",
        "os_name": "android",
        "os_version": "11",
        "device_manufacturer": "Xiaomi",
        "device_model": "Redmi 9A",
        "country_iso_code": ["US", "BR", "IN"][index % 3],
        "app_version_name": "1.0.8" if index % 2 else "1.1.0",
        "app_build_number": "108" if index % 2 else "110",
        "app_package_name": "com.example.selftest",
        "session_id": str(10_000_000_000 + int(moment.timestamp()) // 3600),
    }


def attribution(index: int, reinstall: bool = False) -> dict[str, str]:
    if reinstall or index % 3 == 1:
        return {"publisher_name": "", "tracker_name": "Google Play"}
    if index % 3 == 0:
        return {"publisher_name": "Google Ads", "tracker_name": "UAC campaign"}
    return {"publisher_name": "", "tracker_name": ""}


def generate(rng: random.Random) -> dict[str, dict[date, list[dict[str, str]]]]:
    """{table: {day: rows}} shaped like Logs API CSV rows."""
    data: dict[str, dict[date, list[dict[str, str]]]] = {t.name: {} for t in TABLES}
    for offset in range(DAYS):
        day = START + timedelta(days=offset)
        rows: dict[str, list[dict[str, str]]] = {name: [] for name in data}
        for index in range(DEVICES):
            first_day = index % DAYS == offset
            if index % DAYS > offset or not (first_day or rng.random() < 0.6):
                continue
            moment = datetime(day.year, day.month, day.day, rng.randint(8, 20), rng.randint(0, 59))
            base = base_row(index, moment)
            s = stamp(moment)
            rows["sessions_starts"].append(dict(base, session_start_datetime=s["text"],
                                                session_start_timestamp=s["ts"]))
            if first_day:
                rows["installations"].append(dict(base, **attribution(index), install_datetime=s["text"],
                                                  install_timestamp=s["ts"], is_reinstallation="false"))
                if index == 3:  # a reinstall an hour later, attributed differently
                    later = stamp(moment + timedelta(hours=1))
                    rows["installations"].append(dict(base, **attribution(index, True),
                                                      install_datetime=later["text"],
                                                      install_timestamp=later["ts"],
                                                      is_reinstallation="true"))
            _events(rng, rows, base, moment, index, offset)
        for name in data:
            data[name][day] = rows[name]
    return data


def _events(rng: random.Random, rows: dict, base: dict, moment: datetime, index: int,
            offset: int) -> None:
    second = [0]

    def add(name: str, params: dict | str) -> None:
        second[0] += 7
        s = stamp(moment + timedelta(seconds=second[0]))
        body = params if isinstance(params, str) else json.dumps(params, ensure_ascii=False)
        rows["events"].append(dict(base, event_name=name, event_json=body,
                                   event_datetime=s["text"], event_timestamp=s["ts"]))

    add("session_ping", "")
    for level in range(1, rng.randint(1, 3) + 1):
        add("level_start", {"level": level, "mode": rng.choice(MODES), "attempt": 1})
        params = {"level": level, "result": rng.choice(["win", "lose"]),
                  "duration_sec": round(rng.uniform(20, 200), 2), "stars": rng.randint(0, 3),
                  "is_first": level == 1}
        if index == 0 and offset == 0 and level == 1:
            params["debug_note"] = "rare key"
        add("level_end", params)
    if rng.random() < 0.5:
        add("ad_impression", {"format": "interstitial", "revenue_usd": "0,0123"})
        s = stamp(moment + timedelta(seconds=second[0]))
        rows["ad_revenue_events"].append(dict(
            base, ad_revenue_datetime=s["text"], ad_revenue_timestamp=s["ts"], ad_revenue="0.0123",
            ad_revenue_currency="USD", ad_revenue_type="INTERSTITIAL", ad_revenue_network="AdMob"))
    if index == 5 and offset == 5:
        add("broken_json", "{broken")
    if index == 6:
        add("inventory", {"items": {"a": 1}, "slots": [1, 2]})
    if rng.random() < 0.1:
        rows["crashes"].append(dict(base, crash_datetime=stamp(moment)["text"],
                                    crash="NullReferenceException\n  at Game.Update()",
                                    crash_group_id="null-ref"))
    if rng.random() < 0.1:
        rows["errors"].append(dict(base, error_datetime=stamp(moment)["text"],
                                   error="Addressable load failed", error_id="addressables"))


def expected_params(data: dict) -> int:
    total = 0
    for rows in data["events"].values():
        for row in rows:
            parsed = flatten.parse_json(row["event_json"])
            total += len(parsed.params or {})
    return total


# --------------------------------------------------------------------------- #
# fakes
# --------------------------------------------------------------------------- #

class FakeSource(Source):
    """Serves the synthetic rows as CSV files, records every request."""

    name = "appmetrica"  # the core views read AppMetrica-shaped tables
    token_env = "SELFTEST_TOKEN"

    def __init__(self, data: dict, reject: set[str] | None = None):
        self.data = data
        self.reject = reject or set()
        self.calls: list[tuple[str, date, date, bool, tuple[str, ...]]] = []
        self.warmed: list[tuple[str, date, date]] = []
        extra = {"events": ["bogus_field"]}  # a field the "API" does not know
        self._tables = [dataclasses.replace(t, fields=t.fields + extra.get(t.name, []))
                        for t in TABLES]

    def tables(self) -> list[Table]:
        return self._tables

    def check(self) -> str:
        return "fake source: synthetic data"

    def connect(self) -> dict[str, str]:
        return {"app_id": "42", "app_name": "Selftest", "timezone": "UTC"}

    def first_day(self) -> date | None:
        return START

    def fetch(self, table: Table, fields: list[str], start: date, end: date, dest: Path,
              log: Callable[[str], None], *, fresh: bool = False) -> Path:
        self.calls.append((table.name, start, end, fresh, tuple(fields)))
        bad = [f for f in fields if f in self.reject]
        if bad:
            raise RequestRejected("400", f"Unknown fields: {', '.join(bad)}")
        with dest.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(fields)
            for day, rows in sorted(self.data[table.name].items()):
                if start <= day <= end:
                    writer.writerows([row.get(f, "") for f in fields] for row in rows)
        return dest

    def warm(self, table: Table, fields: list[str], start: date, end: date) -> None:
        self.warmed.append((table.name, start, end))

    def rejected_fields(self, error_text: str, fields: list[str]) -> list[str]:
        return [f for f in fields if f in error_text]


class FakeResponse:
    def __init__(self, status: int, body: bytes = b"", headers: dict[str, str] | None = None):
        self.status = status
        self.headers = Message()
        for key, value in (headers or {}).items():
            self.headers[key] = value
        self._body = io.BytesIO(body)

    def read(self, size: int = -1) -> bytes:
        return self._body.read(size)

    def close(self) -> None:
        pass


class FakeOpener:
    """Answers from a script (responses or exceptions) or a routing function."""

    def __init__(self, script: list | Callable):
        self.script = script
        self.requests: list = []

    def __call__(self, request, timeout):
        self.requests.append(request)
        item = self.script(request) if callable(self.script) else self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    def headers(self, index: int) -> dict[str, str]:
        return {k.lower(): v for k, v in self.requests[index].header_items()}


# --------------------------------------------------------------------------- #
# checks
# --------------------------------------------------------------------------- #

@dataclasses.dataclass
class Lab:
    root: Path
    data: dict
    fake: FakeSource
    log: list[str] = dataclasses.field(default_factory=list)

    @property
    def db(self) -> Path:
        return self.root / "data" / "analytics.db"

    def connect(self) -> sqlite3.Connection:
        return store.connect(self.db)

    def run_sync(self, conn: sqlite3.Connection, *, today: date = TODAY, now: datetime = NOW,
             **options) -> sync.SyncResult:
        self.fake.calls.clear()
        opts = sync.SyncOptions(**{"tables": "all", "chunk_days": 2, "fresh_days": FRESH_DAYS,
                                   "refresh_after_hours": 12, **options})
        return sync.run(conn, self.fake, opts, work_dir=self.root / "data" / "tmp",
                        log=self.log.append, today=today, clock=lambda: now)

    def counts(self, conn: sqlite3.Connection) -> dict[str, int]:
        names = [t.name for t in TABLES] + ["event_params"]
        return {n: conn.execute(f"SELECT COUNT(*) FROM {n}").fetchone()[0] for n in names}


def check_schema(lab: Lab) -> str:
    conn = lab.connect()
    try:
        store.ensure_schema(conn, schema_tables())
        store.ensure_schema(conn, schema_tables())  # idempotent
        expect("bogus_field" not in store.table_columns(conn, "events"), "unexpected column")
        store.ensure_schema(conn, lab.fake.tables())  # a new field becomes a new column
        tables = set(store.list_tables(conn))
        wanted = {t.name for t in TABLES} | {"event_params", "sync_log", "source_fields",
                                             "meta", "imports"}
        expect(wanted <= tables, f"missing tables: {wanted - tables}")
        views = set(store.list_tables(conn, "view"))
        expect({"v_event_catalog", "v_dau", "v_device_first_seen", "v_installs"} <= views,
               f"missing views: {views}")
        columns = {row[1]: row[2] for row in conn.execute("PRAGMA table_info(events)")}
        expect(columns["appmetrica_device_id"] == "TEXT" and columns["event_timestamp"] == "INTEGER",
               f"column types: {columns}")
        expect("event_json_raw" in columns and "bogus_field" in columns, "raw / added columns")
    finally:
        conn.close()
    return f"{len(tables)} tables, {len(views)} views"


def check_range_replace(lab: Lab) -> str:
    conn = lab.connect()
    try:
        # A pending small write must not block the explicit transaction of a chunk.
        store.store_fields(conn, "selftest", "events", ["event_name"], rejected=["x"])
        store.set_meta(conn, "selftest.marker", "1")
        events = lab.fake.table("events")
        rows = [{"event_datetime": "2000-01-01 10:00:00", "event_name": "a", "event_json": '{"k":1}'},
                {"event_datetime": "2000-01-05 10:00:00", "event_name": "b", "event_json": ""},
                {"event_datetime": "", "event_name": "c", "event_json": ""}]
        with store.transaction(conn):
            result = store.replace_range(conn, events, ["event_datetime", "event_name", "event_json"],
                                         rows, date(2000, 1, 1), date(2000, 1, 2), "2000-01-03")
        expect(result.per_day == {"2000-01-01": 2} and result.outside == 1,
               f"per_day {result.per_day}, outside {result.outside}")
        try:
            with store.transaction(conn):
                store.replace_range(conn, events, ["event_name"], [], date(2000, 1, 1),
                                    date(2000, 1, 2), "x")
                raise RuntimeError("rollback")
        except RuntimeError:
            pass
        kept = conn.execute("SELECT COUNT(*) FROM events WHERE date = '2000-01-01'").fetchone()[0]
        expect(kept == 2, "a failed chunk must roll back its delete")
        with store.transaction(conn):
            store.replace_range(conn, events, ["event_name"], [], date(2000, 1, 1),
                                date(2000, 1, 2), "x")
        conn.execute("DELETE FROM source_fields WHERE source = 'selftest'")
        conn.execute("DELETE FROM meta WHERE key = 'selftest.marker'")
    finally:
        conn.close()
    return "outside-range rows skipped, rollback keeps old rows"


def check_sync(lab: Lab) -> str:
    lab.fake.reject = {"bogus_field"}
    conn = lab.connect()
    try:
        result = lab.run_sync(conn)
        counts = lab.counts(conn)
        for name, per_day in lab.data.items():
            expected = sum(len(rows) for rows in per_day.values())
            expect(counts[name] == expected, f"{name}: {counts[name]} rows, expected {expected}")
        expect(counts["event_params"] == expected_params(lab.data), "event_params count")
        expect(result.rows == sum(counts[t.name] for t in TABLES), "summary row count")
        # drift: rejected once, retried without it, remembered
        event_calls = [c for c in lab.fake.calls if c[0] == "events"]
        expect("bogus_field" in event_calls[0][4] and "bogus_field" not in event_calls[1][4],
               "bogus_field was not pruned")
        expect(store.rejected_fields(conn, "appmetrica", "events") == {"bogus_field"},
               "rejected field not stored")
        # ranges: 2-day chunks, fresh flag = range touches the fresh window
        loaded = [c for c in lab.fake.calls if not (c[0] == "events" and "bogus_field" in c[4])]
        expect(len(loaded) == len(TABLES) * DAYS // 2, f"{len(loaded)} requests")
        expect(all(c[3] == (c[2] >= FRESH_EDGE) for c in loaded), "fresh flag per range")
        expect(all(end < FRESH_EDGE for _, _, end in lab.fake.warmed),
               f"a fresh range was warmed: {lab.fake.warmed}")
        finals = conn.execute("SELECT COUNT(*) FROM sync_log WHERE table_name = 'events' "
                              "AND is_final = 1").fetchone()[0]
        expect(finals == (FRESH_EDGE - START).days, f"{finals} final days")
        leftovers = list((lab.root / "data" / "tmp").glob("*"))
        expect(not leftovers, f"temp files left: {leftovers}")
        row = conn.execute("SELECT appmetrica_device_id, typeof(appmetrica_device_id) FROM events "
                           "ORDER BY appmetrica_device_id DESC LIMIT 1").fetchone()
        expect(row[1] == "text" and row[0] == device_id(DEVICES - 1), f"device id {tuple(row)}")
        crash = conn.execute("SELECT crash FROM crashes LIMIT 1").fetchone()
        expect(crash is None or "\n" in crash[0], "embedded newline lost")
        broken = conn.execute("SELECT event_json, event_json_raw FROM events "
                              "WHERE event_name = 'broken_json'").fetchone()
        expect(broken is not None and broken[0] is None and broken[1] == "{broken", "invalid JSON")
        expect(store.get_meta(conn, "appmetrica.app_name") == "Selftest", "meta not stored")
    finally:
        conn.close()
    return f"{sum(counts.values()):,} rows over {len(TABLES)} tables, drift pruned"


def check_idempotent(lab: Lab) -> str:
    conn = lab.connect()
    try:
        before = lab.counts(conn)
        lab.run_sync(conn)
        expect(not lab.fake.calls, f"re-run requested {len(lab.fake.calls)} ranges")
        lab.run_sync(conn, force=True)
        expect(lab.counts(conn) == before, "forced reload changed row counts")
        expect(all("bogus_field" not in c[4] for c in lab.fake.calls), "rejected field requested")
        final = [c for c in lab.fake.calls if c[2] < FRESH_EDGE]
        expect(final and not any(c[3] for c in final), "closed ranges should allow a cached answer")
    finally:
        conn.close()
    return f"re-run: 0 requests; --force: {len(lab.fake.calls)} requests, same counts"


def check_planning(lab: Lab) -> str:
    day = [START + timedelta(days=i) for i in range(4)]
    states = {day[0].isoformat(): store.DayState(True, NOW - timedelta(days=9)),
              day[1].isoformat(): store.DayState(False, NOW - timedelta(hours=2)),
              day[2].isoformat(): store.DayState(False, NOW - timedelta(hours=20))}
    pending, skipped = sync.plan_days(day, states, force=False, refresh_after_hours=12, now=NOW)
    expect(pending == day[2:] and skipped == {"complete": 1, "refreshed < 12h ago": 1},
           f"plan {pending} {skipped}")
    pending, _ = sync.plan_days(day, states, force=False, refresh_after_hours=0, now=NOW)
    expect(pending == day[1:], "refresh-after 0 re-requests every fresh day")
    pending, _ = sync.plan_days(day, states, force=True, refresh_after_hours=12, now=NOW)
    expect(pending == day, "--force requests everything")
    d = [date(2026, 1, n) for n in (1, 2, 3, 5, 6)]
    expect(sync.plan_chunks(d, 2) == [d[0:2], d[2:3], d[3:5]], "chunks break at gaps")

    conn = lab.connect()
    try:
        lab.run_sync(conn, now=NOW + timedelta(hours=13))  # fresh days are stale now
        days = {c[1] + timedelta(days=i) for c in lab.fake.calls for i in range((c[2] - c[1]).days + 1)}
        expect(min(days) == FRESH_EDGE and max(days) == TODAY, f"refreshed {min(days)}..{max(days)}")
        # Five days later the old fresh days are closed: requested once more, rebuilt.
        later = TODAY + timedelta(days=5)
        lab.run_sync(conn, today=later, now=NOW + timedelta(days=5), until=TODAY)
        calls = [c for c in lab.fake.calls if c[0] == "events"]
        expect(calls and all(c[3] for c in calls), "ranges loaded while fresh must be rebuilt")
        open_days = conn.execute("SELECT COUNT(*) FROM sync_log WHERE is_final = 0 AND day < ?",
                                 ((later - timedelta(days=FRESH_DAYS)).isoformat(),)).fetchone()[0]
        expect(open_days == 0, f"{open_days} days stayed open")
    finally:
        conn.close()
    prefetcher = sync.Prefetcher(lab.fake, enabled=True)
    lab.fake.warmed.clear()
    events = lab.fake.table("events")
    prefetcher.warm(events, ["event_name"], [TODAY - timedelta(days=1), TODAY], FRESH_EDGE)
    prefetcher.warm(events, ["event_name"], [START, START + timedelta(days=1)], FRESH_EDGE)
    prefetcher.close(wait=True)
    expect(lab.fake.warmed == [("events", START, START + timedelta(days=1))],
           f"warmed {lab.fake.warmed}")
    return "final/fresh/refresh-after/force, loaded-while-fresh rebuilt, warm only closed ranges"


def check_drift_guard(lab: Lab) -> str:
    conn = lab.connect()
    events = lab.fake.table("events")
    dest = lab.root / "data" / "tmp" / "guard.csv"
    fields = ["event_datetime", "event_name", "event_json"]
    try:
        # The date field is protected; an answer naming every other field is not about fields.
        for reject in ({"event_datetime"}, {"event_name", "event_json"}):
            try:
                sync.fetch_with_drift(conn, FakeSource(lab.data, reject), events, fields,
                                      START, START, dest, quiet, False)
            except RequestRejected:
                continue
            raise AssertionError(f"rejecting {reject} should not be pruned")
    finally:
        dest.unlink(missing_ok=True)
        conn.close()
    return "date field and whole-request rejections are never pruned"


def check_flatten(lab: Lab) -> str:
    parsed = flatten.parse_json('{"a":1,"b":"2,5","c":true,"d":null,"e":{"x":1},'
                                '"f":"text","g":"nan","h":" 7 "}')
    rows = {r[4]: (r[5], r[6]) for r in flatten.param_rows(1, "2026-01-01", "x", "ev", parsed.params)}
    expect(rows["a"] == ("1", 1.0) and rows["b"] == ("2,5", 2.5), f"numbers {rows}")
    expect(rows["c"] == ("true", 1.0) and rows["d"] == (None, None), f"bool/null {rows}")
    expect(rows["e"] == ('{"x":1}', None) and rows["f"][1] is None and rows["g"][1] is None,
           f"nested/text {rows}")
    expect(rows["h"][1] == 7.0, "padded number")
    broken = flatten.parse_json("{oops")
    expect(broken.normalized is None and broken.raw == "{oops", "invalid JSON kept raw")
    listed = flatten.parse_json("[1, 2]")
    expect(listed.normalized == "[1,2]" and listed.params is None, "non-dict JSON")
    conn = store.connect_readonly(lab.db)
    try:
        stored = conn.execute("SELECT key, value_text, value_num FROM event_params "
                              "WHERE event_name = 'ad_impression' AND key = 'revenue_usd' "
                              "LIMIT 1").fetchone()
        expect(tuple(stored) == ("revenue_usd", "0,0123", 0.0123), f"stored {tuple(stored)}")
    finally:
        conn.close()
    return "numbers, decimal commas, bools, nulls, nested, invalid JSON"


def check_catalog(lab: Lab) -> str:
    conn = store.connect_readonly(lab.db)
    try:
        rows, note = catalog.catalog(conn)
        expect(note == "", f"a flattened database must not be sampled: {note}")
        by_pair = {(r.event_name, r.key): r for r in rows}
        level_end = sum(1 for rows_ in lab.data["events"].values() for r in rows_
                        if r["event_name"] == "level_end")
        result = by_pair[("level_end", "result")]
        expect(result.occurrences == level_end and result.events == level_end, "occurrences")
        expect(result.numeric_share == 0.0 and set(result.samples) <= {"win", "lose"},
               f"result stats {result}")
        expect(by_pair[("level_start", "level")].numeric_share == 1.0, "numeric share")
        expect(("session_ping", None) in by_pair, "events without parameters are listed")
        expect(by_pair[("level_end", "debug_note")].occurrences == 1, "rare key")
        filtered, _ = catalog.catalog(conn, min_count=2)
        expect(("level_end", "debug_note") not in {(r.event_name, r.key) for r in filtered},
               "--min-count")
        table = catalog.catalog_table(rows)
        expect(len(table[0]) == len(catalog.CATALOG_COLUMNS), "table shape")
    finally:
        conn.close()
    return f"{len(rows)} event x key rows"


def check_model(lab: Lab) -> str:
    conn = store.connect_readonly(lab.db)
    try:
        result = catalog.scaffold(conn, since=None, min_share=0.1, top=0, generated_on=TODAY)
        wide = catalog.scaffold(conn, since=None, min_share=0.1, top=50, generated_on=TODAY)
    finally:
        conn.close()
    sql = result.sql
    expect('CAST(json_extract(e.event_json, \'$."level"\') AS INTEGER) AS "level"' in sql, "level")
    expect('AS REAL) AS "duration_sec"' in sql and "REPLACE(" in sql, "real / decimal comma")
    expect('json_extract(e.event_json, \'$."result"\') AS "result"' in sql, "text column")
    expect('"debug_note"' not in sql and '"debug_note"' in wide.sql, "--min-share / --top")
    expect("e.appmetrica_device_id AS device_id" in sql, "base columns")
    model = lab.root / "model"
    model.mkdir(exist_ok=True)
    (model / "010_v_events.sql").write_text(sql, encoding="utf-8")
    (model / "020_wins.sql").write_text(
        "-- wins; a ';' inside a literal must not split the statement\n"
        "DROP VIEW IF EXISTS v_wins;\n"
        "CREATE VIEW v_wins AS\n  SELECT * FROM v_events\n  WHERE result = 'win' OR mode = 'a;b';\n",
        encoding="utf-8")
    conn = lab.connect()
    try:
        count = store.apply_sql_files(conn, sorted(model.glob("*.sql")))
        expect(count == 4, f"{count} statements")
        row = conn.execute("SELECT typeof(level), typeof(duration_sec), revenue_usd, typeof(is_first) "
                           "FROM v_events WHERE event_name = 'level_end' LIMIT 1").fetchone()
        expect(tuple(row)[:2] == ("integer", "real") and row[3] == "integer", f"types {tuple(row)}")
        revenue = conn.execute("SELECT revenue_usd FROM v_events WHERE event_name = "
                               "'ad_impression' LIMIT 1").fetchone()[0]
        expect(abs(revenue - 0.0123) < 1e-9, f"revenue {revenue}")
        bad = model / "030_bad.sql"
        bad.write_text("CREATE VIEW v_ok AS SELECT 1 AS x;\n\nCREATE VIEW v_bad AS\n"
                       "  SELECT nope FROM missing_table;\n", encoding="utf-8")
        try:
            store.apply_sql_files(conn, sorted(model.glob("*.sql")))
            raise AssertionError("a broken model file was applied")
        except GakError as error:
            expect("030_bad.sql line 3" in str(error), f"error text: {error}")
        expect("v_ok" not in store.list_tables(conn, "view"), "failed apply left changes")
        bad.unlink()
    finally:
        conn.close()
    return f"{result.columns} typed columns, apply is all-or-nothing"


def check_queries(lab: Lab) -> str:
    project = lab.root / "queries"
    project.mkdir(exist_ok=True)
    (project / "dau.sql").write_text("-- Project DAU\nSELECT date, dau FROM v_dau "
                                     "WHERE date >= :since ORDER BY date;\n", encoding="utf-8")
    found = {q.name: q for q in query.list_queries(lab.root)}
    expect(found["dau"].origin == "project" and found["dau"].overrides, "project override")
    kit = [path for path in sorted(query.KIT_QUERIES.glob("*.sql"))]
    expected = {"overview", "sync_health", "event_volume", "dau", "retention", "installs_by_source",
                "app_versions", "ad_revenue_daily", "crashes_errors"}
    expect(expected <= {p.stem for p in kit}, f"kit queries: {[p.stem for p in kit]}")
    conn = store.connect_readonly(lab.db)
    sizes = {}
    try:
        for path in kit:
            expect(bool(query.title_of(path)), f"{path.name} has no title line")
            sizes[path.stem] = len(query.run_named(conn, path, {}).rows)
        installs = query.run_named(conn, query.KIT_QUERIES / "installs_by_source.sql", {}).rows
        paid, organic, unknown = (sum(r[i] for r in installs) for i in (3, 4, 5))
        expect((paid, organic, unknown) == (9, 11, 10), f"source classes {paid, organic, unknown}")
        retention = query.run_named(conn, query.KIT_QUERIES / "retention.sql", {}).rows
        expect(retention and retention[0][2] is not None and retention[-1][2] is None,
               "retention must stay empty for incomplete days")
        limited = query.run_named(conn, query.KIT_QUERIES / "event_volume.sql",
                                  query.parse_params(["since=2000-01-01"]), limit=2)
        expect(len(limited.rows) == 2 and limited.truncated, "limit / truncated")
        try:
            query.execute(conn, "SELECT :missing_param", {})
            raise AssertionError("missing parameter not reported")
        except GakError as error:
            expect("--param missing_param=" in str(error), str(error))
    finally:
        conn.close()
    empty = [name for name, n in sizes.items() if n == 0]
    expect(not empty, f"queries returned nothing: {empty}")
    return f"{len(kit)} kit queries ran, project override listed"


RU_ADS = (
    "Отчет по кампаниям\n"
    "1 сентября 2026 г. - 20 сентября 2026 г.\n"
    "Кампания;Статус;Показы;Клики;CTR;Сред. цена за клик;Стоимость;Конверсии;Стоимость/конв.\n"
    "Sample Game US;Включено;41{nb}814;698;1,67 %;0,24 $;167,52 $;107,00;1,57 $\n"
    "Sample Game BR;Приостановлено;12 003;120;1,00 %;0,05 $;6,00 $;—;—\n"
    "Итого: аккаунт;;53 817;818;1,52 %;0,21 $;173,52 $;107,00;1,62 $\n"
).replace("{nb}", chr(0xA0))

ADMOB = (
    "Date\tCountry\tAd unit\tAd requests\tMatch rate (%)\tImpressions\teCPM (USD)\t"
    "Estimated earnings (USD)\n"
    "2026-09-01\tUnited States\tInterstitial\t1,234\t87.50%\t1,050\tUS$29.10\tUS$30.56\n"
    "2026-09-01\tBrazil\tRewarded\t800\t92.00%\t700\tUS$3.20\tUS$2.24\n"
    "2026-09-02\tUnited States\tInterstitial\t1,500\t88.10%\t1,300\tUS$31.00\tUS$40.30\n"
)


def check_csv_import(lab: Lab) -> str:
    folder = lab.root / "imports"
    folder.mkdir(exist_ok=True)
    ru = folder / "google_ads_ru.csv"
    ru.write_bytes(b"\xef\xbb\xbf" + RU_ADS.encode("utf-8"))
    admob = folder / "admob_sept.csv"
    admob.write_bytes(b"\xff\xfe" + ADMOB.encode("utf-16-le"))
    expect(csv_import.parse_number("$0.24") == 0.24 and csv_import.parse_number("-") is None,
           "parse_number basics")
    expect(csv_import.parse_number("(1,234.50)") == -1234.5, "accounting negative")
    for text in ("12 matches", "2026-09-01", "01.09.2026", "1.1.23", "< 10%"):
        expect(csv_import.parse_number(text) is None, f"'{text}' must stay text")
    conn = lab.connect()
    try:
        result = csv_import.import_csv(conn, ru, kind="google_ads", display_name="imports/x.csv")
        expect(result.table == "ext_google_ads_ru" and result.rows == 2, f"{result.table} {result.rows}")
        expect(result.encoding == "utf-8-sig" and result.delimiter == ";", "encoding / delimiter")
        expect(result.columns == ["kampaniya", "status", "pokazy", "kliki", "ctr",
                                  "sred_tsena_za_klik", "stoimost", "konversii", "stoimost_konv"],
               f"columns {result.columns}")
        expect(set(result.numeric_columns) == set(result.columns[2:]), f"numeric {result.numeric_columns}")
        expect(len(result.preamble) == 2 and result.skipped and "total" in result.skipped[0],
               f"preamble/total {result.preamble} {result.skipped}")
        us = conn.execute("SELECT pokazy__num, ctr__num, sred_tsena_za_klik__num, stoimost__num, "
                          "konversii__num FROM ext_google_ads_ru WHERE row_no = 1").fetchone()
        expect(tuple(us) == (41814.0, 1.67, 0.24, 167.52, 107.0), f"US row {tuple(us)}")
        br = conn.execute("SELECT pokazy__num, konversii, konversii__num FROM ext_google_ads_ru "
                          "WHERE row_no = 2").fetchone()
        expect(tuple(br) == (12003.0, "—", None), f"BR row {tuple(br)}")
        try:
            csv_import.import_csv(conn, ru, kind="google_ads")
            raise AssertionError("the same file was imported twice")
        except GakError as error:
            expect("already imported" in str(error), str(error))
        csv_import.import_csv(conn, ru, kind="google_ads", replace=True)
        imports = conn.execute("SELECT COUNT(*) FROM imports WHERE table_name = "
                               "'ext_google_ads_ru'").fetchone()[0]
        expect(imports == 1, "--replace keeps one import record")

        result = csv_import.import_csv(conn, admob, kind="admob", table="admob")
        expect(result.table == "ext_admob" and result.encoding == "utf-16" and
               result.delimiter == "tab", f"admob {result.table} {result.encoding} {result.delimiter}")
        expect(result.columns == ["date", "country", "ad_unit", "ad_requests", "match_rate_pct",
                                  "impressions", "ecpm_usd", "estimated_earnings_usd"],
               f"admob columns {result.columns}")
        expect("date" not in result.numeric_columns, "dates are not numbers")
        row = conn.execute("SELECT ad_requests__num, match_rate_pct__num, ecpm_usd__num, "
                           "estimated_earnings_usd__num FROM ext_admob WHERE row_no = 1").fetchone()
        expect(tuple(row) == (1234.0, 87.5, 29.1, 30.56), f"admob row {tuple(row)}")
    finally:
        conn.close()
    return "Russian Google Ads (BOM, ;, spaces, %, $, dash) and UTF-16 AdMob"


def check_http(lab: Lab) -> str:
    waits: list[float] = []
    dest = lab.root / "data" / "tmp" / "http.csv"
    dest.parent.mkdir(parents=True, exist_ok=True)
    body = b"a,b\n1,2\n"
    opener = FakeOpener([FakeResponse(202, b"Progress is 42%"), FakeResponse(202, b"Progress is 96%"),
                         FakeResponse(200, gzip.compress(body), {"Content-Encoding": "gzip"})])
    size = Http(opener=opener, sleep=waits.append).download("https://x/export", {}, dest, quiet,
                                                             no_cache=True)
    expect(size == len(body) and dest.read_bytes() == body, "gzip body")
    expect(waits == [5, 10], f"poll waits {waits}")
    expect(opener.headers(0).get("cache-control") == "no-cache" and
           "cache-control" not in opener.headers(1), "no-cache only before the first 202")

    waits.clear()
    opener = FakeOpener([FakeResponse(429, b"queue", {"Retry-After": "7"}),
                         ConnectionResetError("reset"), FakeResponse(200, body)])
    Http(opener=opener, sleep=waits.append).download("https://x/export", {}, dest, quiet)
    expect(waits == [7, 5], f"429 / network retry waits {waits}")

    waits.clear()
    opener = FakeOpener([FakeResponse(503, b"down") for _ in range(5)])
    try:
        Http(opener=opener, sleep=waits.append, retries=4).download("https://x", {}, dest, quiet)
        raise AssertionError("503 forever should fail")
    except HttpError as error:
        expect(error.status == 503 and waits == [5, 15, 30, 60], f"5xx retries {waits}")
    try:
        Http(opener=FakeOpener([FakeResponse(400, b"bad field foo")]), sleep=waits.append).download(
            "https://x", {}, dest, quiet)
        raise AssertionError("400 should fail at once")
    except HttpError as error:
        expect(error.status == 400 and error.text == "bad field foo", "400 text")
    future = time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime(time.time() + 120))
    expect(100 <= parse_retry_after(future) <= 120 and parse_retry_after("15") == 15, "Retry-After")
    dest.unlink(missing_ok=True)
    return "202 polling, 429 Retry-After, retries, 5xx give-up, gzip"


def check_appmetrica(lab: Lab) -> str:
    token = "selftest-secret-token"
    apps = {"applications": [
        {"id": 1, "name": "Other", "api_key": "key-a", "create_date": "2025-01-01", "time_zone_name": "UTC"},
        {"id": 2, "name": "Game", "api_key": "key-b", "create_date": "2026-08-01 10:00:00",
         "time_zone_name": "Europe/Moscow"}]}

    def route(request):
        url = request.full_url
        if "/management/v1/applications" in url:
            return FakeResponse(200, json.dumps(apps).encode())
        if "parts_count=2" in url:
            first = "part_number=0" in url  # the first part ends without a newline
            body = "event_name,event_datetime\n{},2026-09-01 10:00:00{}".format(
                "A" if first else "B", "" if first else "\n")
            return FakeResponse(200, body.encode())
        return FakeResponse(400, b"Try to use more parts.")

    opener = FakeOpener(route)
    source = AppMetricaSource({"api_key": "key-b"}, token, "selftest", quiet,
                              http=Http(opener=opener, sleep=quiet))
    meta = source.connect()
    expect(meta["app_id"] == "2" and meta["timezone"] == "Europe/Moscow", f"meta {meta}")
    expect(source.first_day() == date(2026, 8, 1), "first day from create_date")
    dest = lab.root / "data" / "tmp" / "am.csv"
    source.fetch(source.table("events"), ["event_name", "event_datetime"], date(2026, 9, 1),
                 date(2026, 9, 7), dest, quiet, fresh=True)
    lines = dest.read_text(encoding="utf-8").splitlines()
    expect(lines == ["event_name,event_datetime", "A,2026-09-01 10:00:00", "B,2026-09-01 10:00:00"],
           f"parts glued {lines}")
    expect(all(token not in r.full_url for r in opener.requests), "token leaked into a URL")
    expect(all(dict(r.header_items()).get("Authorization") == f"OAuth {token}"
               for r in opener.requests), "authorization header")
    part_one = [r for r in opener.requests if "part_number=1" in r.full_url][0]
    expect("Cache-control" not in dict(part_one.header_items()), "later parts must reuse the report")
    expect(source.rejected_fields("Unknown field: city_v2, os_name", ["city", "os_name"]) == ["os_name"],
           "rejected_fields matches whole names")
    denied = AppMetricaSource({"app_id": "2"}, token, "selftest", quiet,
                              http=Http(opener=FakeOpener(lambda r: FakeResponse(401, b"no")), sleep=quiet))
    try:
        denied.connect()
        raise AssertionError("401 not reported")
    except SourceError as error:
        expect("401" in str(error) and token not in str(error), str(error))
    AppMetricaSource({"app_id": "2"}, token, "t", quiet, http=Http(
        opener=FakeOpener(lambda r: OSError("down")), sleep=quiet)).warm(
        source.table("events"), ["event_name"], START, START)  # must not raise
    dest.unlink(missing_ok=True)
    return "app lookup by api_key, parts glued, token only in the header, 401 message"


def run_cli(lab: Lab, *argv: str) -> tuple[int, str, str]:
    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = cli.main(list(argv), analytics_dir=lab.root)
    return code, stdout.getvalue(), stderr.getvalue()


def check_cli(lab: Lab) -> str:
    (lab.root / "imports" / "play.csv").write_text("Date,Store listing visitors,Acquisitions\n"
                                                   "2026-09-01,120,30\n", encoding="utf-8")
    cases = [
        (("status",), 0, "fresh window"),
        (("query", "list"), 0, "overrides the kit query"),
        (("query", "overview", "--format", "md"), 0, "| date |"),
        (("query", "event_volume", "--format", "csv", "--limit", "2"), 0, "event_name,events"),
        (("sql", "SELECT COUNT(*) AS n FROM events", "--format", "json"), 0, '"n":'),
        (("catalog", "--format", "md", "--min-count", "5"), 0, "catalog:"),
        (("model", "scaffold"), 1, "belongs to the project"),
        (("model", "scaffold", "--force"), 0, "parameter column"),
        (("model", "apply"), 0, "v_events"),
        (("import-csv", "imports/play.csv", "--kind", "play_console"), 0, "ext_play"),
        (("sql", "DELETE FROM events"), 1, "readonly"),
        (("query", "no_such_query"), 1, "unknown query"),
        (("report", "index"), 0, "index.html"),
    ]
    for argv, code_wanted, needle in cases:
        code, output, errors = run_cli(lab, *argv)
        text = output + errors
        expect(code == code_wanted and needle in text,
               f"`{' '.join(argv)}` exit {code} (wanted {code_wanted}), missing '{needle}': "
               f"{text.strip()[-300:]}")
        if code:
            expect(errors.startswith("error: ") and errors.count("\n") == 1, f"error line: {errors!r}")
    args = cli.build_parser().parse_args(["sync", "--tables", "events", "--since", "2026-09-01",
                                          "--chunk-days", "3"])
    options = cli._sync_options(args, cli.Context(lab.root).config.source("appmetrica"))
    expect(options.tables == "events" and options.since == date(2026, 9, 1) and
           options.chunk_days == 3 and options.fresh_days == 7, f"sync options {options}")
    return f"{len(cases)} commands"


def check_jobs(lab: Lab) -> str:
    """Detached sync bookkeeping: flag stripping, state, wait on finished and dead jobs."""
    from gak import jobs
    child = cli._strip_job_flags(["sync", "--background", "--tables", "events", "--wait",
                                  "--timeout", "30", "--since", "2026-09-01", "--timeout=5"])
    expect(child == ["sync", "--tables", "events", "--since", "2026-09-01"], f"stripped {child}")
    data = lab.root / "jobs"
    data.mkdir(exist_ok=True)
    state_path, log_path = jobs.paths(data)
    lines: list[str] = []
    expect(jobs.wait(data, 1, lines.append) == 0 and "no background sync" in lines[-1], "wait without job")
    log_path.write_text("line one\nline two\n", encoding="utf-8")
    state_path.write_text(json.dumps({"pid": os.getpid(), "status": "running",
                                      "started_at": "t0", "log": jobs.LOG_NAME}), encoding="utf-8")
    try:
        jobs.ensure_idle(data)  # the running job is this very process: allowed
    except Exception as error:  # noqa: BLE001
        raise AssertionError(f"ensure_idle refused its own pid: {error}")
    os.environ[jobs.ENV_STATE] = str(state_path)
    try:
        jobs.finish(0)
    finally:
        del os.environ[jobs.ENV_STATE]
    lines.clear()
    code = jobs.wait(data, 1, lines.append)
    expect(code == 0 and "line two" in lines and "done" in lines[-1], f"wait on finished: {code} {lines}")
    state_path.write_text(json.dumps({"pid": 999999, "status": "running", "started_at": "t0"}),
                          encoding="utf-8")
    lines.clear()
    code = jobs.wait(data, 1, lines.append)
    expect(code == 1 and "gone" in lines[-1], f"wait on a dead job: {code} {lines}")
    expect("died" in (jobs.describe(data) or ""), "status line for a dead job")
    return "flags, finish, wait, dead job"


def table_devices(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[0] for r in conn.execute(f"SELECT DISTINCT appmetrica_device_id FROM {table}")}


def check_sampling(lab: Lab) -> str:
    """Device sampling: the crc32 rule, identical for every table, fixed per database."""
    rate = 0.3
    threshold = sync.sample_threshold(rate)
    expect(sync.keep_device("", threshold) and sync.keep_device(None, threshold),
           "rows without a device id are kept")
    count = sync.RowCount()
    rows = list(sync.sampled(iter([{"d": ""}, {"d": device_id(1)}, {"d": device_id(2)}]), "d", 0,
                             count))
    expect(rows == [{"d": ""}] and (count.read, count.kept) == (3, 1), f"sampled {rows} {count}")
    wanted = {device_id(i) for i in range(DEVICES) if sync.keep_device(device_id(i), threshold)}
    expect(0 < len(wanted) < DEVICES, f"{len(wanted)} of {DEVICES} devices kept")
    conn = store.connect(lab.root / "data" / "sample.db")
    try:
        store.ensure_schema(conn, lab.fake.tables())
        lab.run_sync(conn, sample=rate)
        for table in ("events", "sessions_starts", "installations", "ad_revenue_events"):
            source_rows = [r for rows_ in lab.data[table].values() for r in rows_]
            expected = {r["appmetrica_device_id"] for r in source_rows} & wanted
            expect(table_devices(conn, table) == expected, f"{table}: other devices than the rule")
            stored = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            expect(stored == sum(r["appmetrica_device_id"] in wanted for r in source_rows),
                   f"{table}: {stored} rows")
        expect(store.get_meta(conn, "appmetrica.sample_rate") == "0.3", "rate not recorded")
        expect(any("of devices" in line for line in lab.log), "sync must say it samples")
        lab.run_sync(conn, sample=rate)  # same rate: accepted
        for other, target in ((0.5, conn), (0.3, None)):
            target = target or store.connect(lab.db)  # the full-rate database refuses 0.3
            try:
                lab.run_sync(target, sample=other, dry_run=True)
                raise AssertionError(f"sample {other} was accepted into a database of another rate")
            except GakError as error:
                expect("--db" in str(error) and "mix" in str(error), str(error))
            finally:
                if target is not conn:
                    target.close()
    finally:
        conn.close()
    return f"{len(wanted)} of {DEVICES} devices, same set in every table, other rates refused"


def check_no_flatten(lab: Lab) -> str:
    """flatten_params = false: no event_params, catalog and scaffold read event_json."""
    db = lab.root / "data" / "noflat.db"
    conn = store.connect(db)
    try:
        store.ensure_schema(conn, lab.fake.tables())
        lab.run_sync(conn, flatten=False)
        expect(conn.execute("SELECT COUNT(*) FROM event_params").fetchone()[0] == 0,
               "event_params was written")
        expect(store.get_meta(conn, "appmetrica.flatten_params") == "0", "setting not recorded")
    finally:
        conn.close()
    sampled_db, full_db = store.connect_readonly(db), store.connect_readonly(lab.db)
    try:
        rows, note = catalog.catalog(sampled_db)
        full, _ = catalog.catalog(full_db)
        expect("event_json" in note and "all " in note, f"note: {note}")

        def shape(items: list) -> set:
            return {(r.event_name, r.key, r.occurrences, r.devices, r.distinct_values,
                     round(r.numeric_share or 0, 6), tuple(r.samples)) for r in items}

        expect(shape(rows) == shape(full), f"catalog differs: {shape(rows) ^ shape(full)}")
        _, few = catalog.catalog(sampled_db, max_events=50)
        expect("latest 50 of" in few, f"bounded sample note: {few}")
        lean = catalog.scaffold(sampled_db, since=None, min_share=0.1, top=0, generated_on=TODAY)
        rich = catalog.scaffold(full_db, since=None, min_share=0.1, top=0, generated_on=TODAY)
        body = [line for line in lean.sql.splitlines() if not line.startswith("--")]
        expect(body == [line for line in rich.sql.splitlines() if not line.startswith("--")],
               "scaffold from event_json differs from the flattened one")
        expect("-- Parameters: event_params is not filled" in lean.sql, "scaffold note")
    finally:
        sampled_db.close()
        full_db.close()
    return "event_params empty; catalog and scaffold match the flattened database"


def check_disk_guard(lab: Lab) -> str:
    """A chunk that would crowd the disk is refused before parsing; WAL is truncated."""
    db = lab.root / "data" / "guard.db"
    conn = store.connect(db)
    usage = shutil.disk_usage
    try:
        store.ensure_schema(conn, lab.fake.tables())
        sync.shutil.disk_usage = lambda path: usage(path)._replace(free=4096)
        try:
            lab.run_sync(conn, tables="events")
            raise AssertionError("a chunk larger than the free space was loaded")
        except GakError as error:
            for needle in ("the CSV is", "would grow by", "only 4.0 KB are free",
                           "--sample 0.1", "--no-flatten", "--since"):
                expect(needle in str(error), f"missing '{needle}': {error}")
        finally:
            sync.shutil.disk_usage = usage
        expect(conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0, "rows loaded")
        expect(not list((lab.root / "data" / "tmp").glob("*.csv")), "CSV left behind")
        warn_at = sync.WARN_CSV_BYTES
        sync.WARN_CSV_BYTES = 0
        try:
            lab.run_sync(conn, tables="events")
        finally:
            sync.WARN_CSV_BYTES = warn_at
        expect(any("warning: the CSV is" in line for line in lab.log), "no warning for a big CSV")
        expect(any("rows/s" in line and "CSV" in line for line in lab.log), "no throughput line")
        wal = Path(str(db) + "-wal")
        expect(not wal.exists() or wal.stat().st_size == 0, "the WAL was not truncated")
    finally:
        conn.close()
    return "refused with sizes and levers, warning above the threshold, WAL truncated"


def raw_activity(data: dict) -> dict[str, dict]:
    """Independent reference for the standard tables, straight from the synthetic rows."""
    devices: dict[str, dict] = {}
    for day, rows in data["events"].items():
        for row in rows:
            d = devices.setdefault(row["appmetrica_device_id"], {
                "days": set(), "sessions": {}, "version": row["app_version_name"], "names": set()})
            d["days"].add(day)
            d["names"].add(row["event_name"])
            d["sessions"].setdefault(row["session_id"], []).append(int(row["event_timestamp"]))
    for d in devices.values():
        d["first"] = min(d["days"])
        # gaps inside a session are 7 s, far below the cap: active time = last - first event
        d["active"] = sum(max(ts) - min(ts) for ts in d["sessions"].values())
    return devices


def check_standard_tables(lab: Lab) -> str:
    """keymetrics / dropoff against a reference computed from the raw synthetic rows."""
    from gak import metrics
    ref = raw_activity(lab.data)
    last = max(day for day, rows_ in lab.data["events"].items() if rows_)
    inter: dict[str, int] = {}
    for rows_ in lab.data["ad_revenue_events"].values():
        for row in rows_:
            inter[row["appmetrica_device_id"]] = inter.get(row["appmetrica_device_id"], 0) + 1
    conn = store.connect_readonly(lab.db)
    try:
        km = metrics.key_metrics(conn, by="version")
        rows = {r.key: r for r in km.rows}
        expect(km.population.source.startswith("every device"), f"population {km.population.source}")
        for group in km.groups:
            members = [k for k, d in ref.items() if group == metrics.ALL or d["version"] == group]
            expect(rows["players"].values[group] == len(members), f"players {group}")
            base = [k for k in members if (last - ref[k]["first"]).days > 1]
            d1 = 100.0 * sum(ref[k]["first"] + timedelta(days=1) in ref[k]["days"] for k in base) / len(base)
            expect(rows["d1"].n[group] == len(base) and abs(rows["d1"].values[group] - d1) < 1e-9,
                   f"D1 {group}: {rows['d1'].values[group]} vs {d1}")
            sessions = sum(len(ref[k]["sessions"]) for k in members) / len(members)
            expect(abs(rows["sessions"].values[group] - sessions) < 1e-9, f"sessions {group}")
            active = sum(ref[k]["active"] for k in members) / len(members) / 60
            expect(abs(rows["playtime"].values[group] - active) < 1e-9, f"active time {group}")
            ads = sum(inter.get(k, 0) for k in members) / len(members)
            expect(abs(rows["ads_interstitial"].values[group] - ads) < 1e-9, f"interstitials {group}")
        expect("players_est" not in rows, "no estimate rows at full rate")
        page = metrics.render_key_metrics(km, "html", "ru")
        expect('class="kpi"' in page and "Retention D1" in page and "Все игроки" in page, "html table")
        expect("1.0.8" in metrics.render_key_metrics(km, "md", "en"), "md table")

        steps = ("SELECT appmetrica_device_id AS device_id, CASE event_name WHEN 'session_ping' THEN 1 "
                 "WHEN 'level_start' THEN 2 WHEN 'level_end' THEN 3 END AS step_no, event_name AS step_name "
                 "FROM events WHERE event_name IN ('session_ping', 'level_start', 'level_end')")
        drop = metrics.dropoff(conn, steps=steps, step_sec=10, max_sec=60)
        by_step = {r.label: r.reached for r in drop.rows if r.section == "steps"}
        expect(by_step["level_end"] == sum("level_end" in d["names"] for d in ref.values()), f"steps {by_step}")
        for r in drop.rows:
            if r.section == "time" and r.seconds:
                expect(r.reached == sum(d["active"] >= r.seconds for d in ref.values()),
                       f"time {r.label}: {r.reached}")
        chain = [r.reached for r in drop.rows if r.section == "time"]
        expect(chain == sorted(chain, reverse=True) and chain[0] == len(ref), f"time chain {chain}")
        timed = metrics.dropoff(conn, steps=steps.replace("AS step_name", "AS step_name, 1.5 AS sec"), max_sec=30)
        first = next(r for r in timed.rows if r.section == "steps" and r.label)
        expect(first.sec_median == 1.5 and first.sec_max == 1.5, f"step time {first}")
        expect("step_sec_median" in metrics.render_dropoff(timed, "csv", "en"), "step time columns")
        few = metrics.key_metrics(conn, by="version", min_devices=10_000)
        expect(few.groups == [metrics.ALL] and "under 10000 devices" in few.notes[0], f"min devices {few.notes}")
        one = metrics.dropoff(conn, players="SELECT device_id FROM v_device_first_seen WHERE first_country = 'US'")
        expect(one.rows[0].reached == sum(1 for i in range(DEVICES) if i % 3 == 0), "--players SELECT")
        try:
            metrics.dropoff(conn, players="no_such_view")
            raise AssertionError("a missing --players view was accepted")
        except GakError as error:
            expect("does not work" in str(error), str(error))
        svg = metrics.dropoff_svg(drop, "en")
        expect(svg.startswith("<svg") and "s-bad" in svg, "drop-off chart")
    finally:
        conn.close()
    sampled = store.connect_readonly(lab.root / "data" / "sample.db")
    try:
        km = metrics.key_metrics(sampled, by="none")
        rows = {r.key: r for r in km.rows}
        players = rows["players"].values[metrics.ALL]
        expect(abs(rows["players_est"].values[metrics.ALL] - players / 0.3) < 1e-9, "estimate row")
        expect("estimate" in metrics.render_key_metrics(km, "table", "en"), "estimate rows in the table")
    finally:
        sampled.close()
    for argv, needle in ((("keymetrics", "--format", "html", "--out", "reports/t/keymetrics.html"), "wrote"),
                         (("dropoff", "--svg", f"{lab.root.name}/reports/t/drop.svg", "--max-sec", "60"), "0:30")):
        code, output, errors = run_cli(lab, *argv)
        expect(code == 0 and needle in output, f"`{' '.join(argv)}`: {code} {errors.strip()[-200:]}")
    expect((lab.root / "reports" / "t" / "keymetrics.html").is_file(), "--out relative to analytics/")
    check_sequences(lab)
    expect((lab.root / "reports" / "t" / "drop.svg").is_file(), "--svg with the analytics folder as prefix")
    return (f"key metrics, drop-off, ordinals and leaving for {len(ref)} devices match the raw rows; "
            f"sample estimates")


def raw_stream(data: dict) -> dict[str, list[tuple[int, str, str]]]:
    """device -> [(ts, name, session)] in time order, straight from the synthetic rows."""
    stream: dict[str, list[tuple[int, str, str]]] = {}
    for rows_ in data["events"].values():
        for row in rows_:
            stream.setdefault(row["appmetrica_device_id"], []).append(
                (int(row["event_timestamp"]), row["event_name"], row["session_id"]))
    for items in stream.values():
        items.sort()
    return stream


def check_sequences(lab: Lab) -> None:
    """ordinals / leaving against the raw rows (part of the standard-tables check)."""
    from gak import sequences
    stream = raw_stream(lab.data)
    conn = store.connect_readonly(lab.db)
    try:
        result = sequences.ordinals(conn, events="level_start")
        by_n = {r.n: r for r in result.rows}
        for n in (1, 2, 3):
            want = {d for d, items in stream.items()
                    if any(sum(1 for _, name, s in items if s == sid and name == "level_start") >= n
                           for sid in {s for _, _, s in items})}
            expect(by_n[n].devices == len(want), f"ordinal {n}: {by_n[n].devices} vs {len(want)}")
        expect(by_n[1].sec_median == 7, f"the first level starts 7 s into the session: {by_n[1].sec_median}")
        page = sequences.render_ordinals(result, "html", "ru")
        expect("level_start" in page and "Медиана" in page, "ordinals html")

        pause = ("SELECT appmetrica_device_id AS device_id, event_timestamp AS ts FROM events "
                 "WHERE event_name = 'ad_impression'")
        left = sequences.leaving(conn, events="level_end", pause_events=pause, ignore="ad_impression")
        row = left.rows[0]
        paused, stopped, never = set(), set(), set()
        for device, items in stream.items():
            for i, (ts, name, _) in enumerate(items):
                if name != "level_end":
                    continue
                after = items[i + 1:]
                near = [e for e in after if e[0] - ts <= 20]
                if not after:
                    never.add(device)
                if not [e for e in near if e[1] not in ("ad_impression", "level_end")]:
                    stopped.add(device)
                if any(e[1] == "ad_impression" for e in near):
                    paused.add(device)
        expect((row.paused, row.stopped, row.never_back) == (len(paused), len(stopped), len(never)),
               f"leaving {row} vs paused {len(paused)} stopped {len(stopped)} never {len(never)}")
        expect("level_end" in sequences.render_leaving(left, "html", "ru"), "leaving html")
        expect(sequences.source_label(pause, "ru").startswith("фильтр"), "a SELECT is not printed in notes")
    finally:
        conn.close()
    code, output, errors = run_cli(lab, "leaving", "--events", "level_end,level_start", "--format", "md")
    expect(code == 0 and "| level_end |" in output, f"leaving cli: {code} {errors.strip()[-200:]}")
    code, output, errors = run_cli(lab, "ordinals", "--events", "level_end", "--max-n", "2")
    expect(code == 0 and "level_end" in output, f"ordinals cli: {code} {errors.strip()[-200:]}")


CHECKS: list[tuple[str, Callable[[Lab], str]]] = [
    ("schema", check_schema),
    ("range replace", check_range_replace),
    ("sync", check_sync),
    ("idempotent reload", check_idempotent),
    ("planning", check_planning),
    ("drift guard", check_drift_guard),
    ("flatten", check_flatten),
    ("catalog", check_catalog),
    ("model scaffold + apply", check_model),
    ("queries", check_queries),
    ("csv import", check_csv_import),
    ("http", check_http),
    ("appmetrica source", check_appmetrica),
    ("cli", check_cli),
    ("background jobs", check_jobs),
    ("device sampling", check_sampling),
    ("no flatten", check_no_flatten),
    ("disk guard", check_disk_guard),
    ("standard tables", check_standard_tables),
]


def main() -> int:
    started = time.time()
    root = Path(tempfile.mkdtemp(prefix="gak-selftest-"))
    failures = 0
    try:
        (root / "analytics.toml").write_text(CONFIG, encoding="utf-8")
        data = generate(random.Random(42))
        lab = Lab(root, data, FakeSource(data))
        for name, check in CHECKS:
            lab.log.clear()
            try:
                print(f"ok    {name}: {check(lab)}", flush=True)
            except Exception as error:  # noqa: BLE001 - report every failing check
                failures += 1
                where = traceback.extract_tb(error.__traceback__)[-1]
                print(f"FAIL  {name}: {type(error).__name__}: {error} "
                      f"({Path(where.filename).name}:{where.lineno})", flush=True)
                for line in lab.log[-5:]:
                    print(f"      log: {line}")
    finally:
        shutil.rmtree(root, ignore_errors=True)
    seconds = time.time() - started
    if failures:
        print(f"selftest: {failures} of {len(CHECKS)} checks FAILED ({seconds:.1f}s)")
        return 1
    print(f"selftest: all {len(CHECKS)} checks passed ({seconds:.1f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
