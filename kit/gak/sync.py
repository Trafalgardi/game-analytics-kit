"""Generic sync: which days to request, in which ranges, and how to store them.

Source-agnostic on purpose - a Source only downloads one range of one table to
a CSV file. The rules below each cost real time once (docs/KNOWLEDGE.md, A):
- Days are requested in contiguous ranges (7 days by default), not one by one:
  exports are prepared one after another and a one-day export waits about as
  long as a week.
- A range replaces all of its days in one transaction (store.replace_range),
  so re-running a sync is idempotent.
- A day older than fresh_days is final: nothing more arrives for it, so it is
  never requested again (only with --force). A fresh day is re-requested only
  when its last load is older than refresh_after_hours - re-pulling the same
  hour over and over just burns the export quota.
- A range that is fresh, or holds a day loaded while it was fresh, asks for a
  rebuilt answer; otherwise the source may replay the stale file it cached.
- While one range downloads, the next closed range is warmed up in the
  background: preparation dominates the wall time of a backfill.
- A field the source rejects is dropped from the request and remembered, so a
  lagging API doc costs one NULL column instead of a failed sync.
- The CSV is downloaded to a temp file and parsed from there, never from the
  socket.

Big games (a 7-day events export of 1.4 GB, 3-4 M rows) outgrow a laptop disk:
flattening 20-30 parameters per event into event_params costs ~6 KB per event.
Hence three levers and one guard:
- sample: keep a deterministic share of devices (crc32 of the device id), the
  same rule for every table so per-device joins stay whole; the rate is fixed
  per database because mixed rates would make every count meaningless;
- flatten_params = false: skip event_params (catalog and scaffold then read
  event_json of recent events);
- the disk guard projects the growth of a downloaded chunk before parsing it
  and refuses a chunk that would fill the disk, naming the levers;
- a WAL checkpoint after every chunk, so the WAL does not keep a second copy.
"""

from __future__ import annotations

import csv
import shutil
import sqlite3
import time
import zlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Iterator, Sequence

from . import GakError, store
from .http import human_size
from .sources.base import Log, RequestRejected, Source, Table

# Crash stack traces exceed the csv module's 128 KB default field limit.
csv.field_size_limit(2**31 - 1)

ROW_LOG_STEP = 100_000
SAMPLE_BUCKETS = 10_000

# Database growth per downloaded CSV byte, measured with the selftest generator
# (docs/DESIGN.md section 5): tables stored as is grew 1.1-1.6x; events with
# event_params grew 3.2x at ~3 parameters per event and 5.4x at 25 (~140 bytes
# per parameter: the row plus three indexes). The constants round those up;
# after the first chunk of a table the ratio it really showed is used when larger.
PLAIN_FACTOR = 1.6
FLATTEN_FACTOR = 6.0
WAL_COPY = 2               # measured: the WAL grows as large as the chunk until the checkpoint
FREE_SHARE = 0.6           # refuse a chunk whose peak needs more of the free space
WARN_CSV_BYTES = 500 * 1024 * 1024


@dataclass
class SyncOptions:
    tables: str | list[str] | None = None  # None/"default", "all", or names
    since: date | None = None
    until: date | None = None
    chunk_days: int = 7
    fresh_days: int = 7
    refresh_after_hours: float = 12.0
    force: bool = False
    dry_run: bool = False
    prefetch: bool = True
    with_device_ids: bool = False
    recheck_fields: bool = False  # request fields the remote rejected before
    sample: float = 1.0           # share of devices kept, 0 < sample <= 1
    flatten: bool = True          # write event_params


@dataclass
class TableResult:
    table: str
    days: int = 0
    chunks: int = 0
    rows: int = 0


@dataclass
class SyncResult:
    tables: list[TableResult] = field(default_factory=list)
    seconds: float = 0.0

    @property
    def rows(self) -> int:
        return sum(t.rows for t in self.tables)


# --------------------------------------------------------------------------- #
# planning
# --------------------------------------------------------------------------- #

def resolve_tables(source: Source, spec: str | Sequence[str] | None) -> list[Table]:
    tables = source.tables()
    if spec in (None, "", "default"):
        return [t for t in tables if t.default]
    if spec == "all":
        return tables
    names = [n.strip() for n in (spec.split(",") if isinstance(spec, str) else spec)]
    return [source.table(name) for name in names if name]


def date_range(since: date, until: date) -> list[date]:
    return [since + timedelta(days=i) for i in range((until - since).days + 1)]


def plan_days(days: Sequence[date], states: dict[str, store.DayState], *, force: bool,
              refresh_after_hours: float, now: datetime) -> tuple[list[date], dict[str, int]]:
    """Days to request, and how many were skipped for which reason."""
    pending: list[date] = []
    skipped: dict[str, int] = {}
    recent = f"refreshed < {refresh_after_hours:g}h ago"
    for day in days:
        state = states.get(day.isoformat())
        if force or state is None:
            pending.append(day)
        elif state.is_final:
            skipped["complete"] = skipped.get("complete", 0) + 1
        elif (refresh_after_hours > 0 and state.loaded_at is not None
              and (now - state.loaded_at).total_seconds() < refresh_after_hours * 3600):
            skipped[recent] = skipped.get(recent, 0) + 1
        else:
            pending.append(day)
    return pending, skipped


def plan_chunks(days: Sequence[date], size: int) -> list[list[date]]:
    """Group days into contiguous runs of at most `size` days.

    A gap means those days are already loaded and final: breaking the run there
    avoids paying for data the database already has.
    """
    chunks: list[list[date]] = []
    run: list[date] = []
    for day in days:
        if run and (day - run[-1]).days != 1:
            chunks.extend(_split(run, size))
            run = []
        run.append(day)
    if run:
        chunks.extend(_split(run, size))
    return chunks


def _split(run: list[date], size: int) -> list[list[date]]:
    return [run[i:i + size] for i in range(0, len(run), max(1, size))]


# --------------------------------------------------------------------------- #
# sampling, settings that are fixed per database, disk guard
# --------------------------------------------------------------------------- #

def sample_threshold(rate: float) -> int:
    return round(rate * SAMPLE_BUCKETS)


def keep_device(device_id: str | None, threshold: int) -> bool:
    """Whether a device is in the sample; rows without a device id are always kept."""
    if threshold >= SAMPLE_BUCKETS or not device_id:
        return True
    return zlib.crc32(device_id.encode("utf-8")) % SAMPLE_BUCKETS < threshold


@dataclass
class RowCount:
    read: int = 0
    kept: int = 0


def sampled(rows: Iterator[dict[str, str]], device_field: str | None, threshold: int,
            count: RowCount) -> Iterator[dict[str, str]]:
    """Rows of the sampled devices, applied before insertion; counts both sides."""
    for row in rows:
        count.read += 1
        if device_field is None or keep_device(row.get(device_field), threshold):
            count.kept += 1
            yield row


def describe_sample(rate: float) -> str:
    if sample_threshold(rate) >= SAMPLE_BUCKETS:
        return "all devices"
    return f"{rate * 100:g}% of devices — multiply absolute counts by {1 / rate:.3g}"


def apply_settings(conn: sqlite3.Connection, source: str, options: SyncOptions, log: Log) -> None:
    """Refuse a sample rate that differs from the data already here; record both settings.

    Two rates in one database would turn every count and every per-device join
    into nonsense, so the rate of the first sync sticks (a database synced
    before sampling existed holds all devices).
    """
    has_data = conn.execute("SELECT 1 FROM sync_log WHERE source = ? LIMIT 1",
                            (source,)).fetchone() is not None
    stored = store.get_meta(conn, f"{source}.sample_rate")
    if has_data:
        rate = float(stored) if stored else 1.0
        if sample_threshold(rate) != sample_threshold(options.sample):
            db = store.db_file(conn)
            raise GakError(f"this database holds {rate * 100:g}% of devices (sample {rate:g}); "
                           f"--sample {options.sample:g} would mix two samples. Sync with "
                           f"--sample {rate:g}, or start over in a new --db (or delete {db})")
        previous = store.get_meta(conn, f"{source}.flatten_params")
        if previous is not None and previous != str(int(options.flatten)):
            log("note: flatten_params changed to " + (
                "true: event_params covers only days loaded from now on; "
                "`sync --force --since D` reloads older days" if options.flatten else
                "false: catalog and scaffold read event_json from now on; "
                "event_params keeps the rows of days loaded before"))
    if not options.dry_run:
        store.set_meta(conn, f"{source}.sample_rate", f"{options.sample:g}")
        store.set_meta(conn, f"{source}.flatten_params", str(int(options.flatten)))


def projected_growth(csv_bytes: int, sample: float, flattening: bool,
                     observed: float = 0.0) -> int:
    factor = max(FLATTEN_FACTOR if flattening else PLAIN_FACTOR, observed)
    return int(csv_bytes * sample * factor)


def check_disk(label: str, csv_bytes: int, growth: int, folder: Path, log: Log) -> None:
    """Refuse a chunk whose peak (growth plus the WAL copy) would crowd the free space.

    The peak, not the growth, is what fills a disk: the chunk's pages sit in the
    WAL until the checkpoint copies them into the database file.
    """
    free = shutil.disk_usage(folder).free
    peak = growth * WAL_COPY
    sizes = (f"the CSV is {human_size(csv_bytes)}; the database would grow by "
             f"~{human_size(growth)} (peak ~{human_size(peak)} with the WAL copy)")
    if peak > FREE_SHARE * free:
        raise GakError(f"{label}: {sizes}, but only {human_size(free)} are free on {folder}. "
                       "Load less: --sample 0.1 keeps 10% of devices, --no-flatten skips "
                       "event_params (the largest part), a shorter --since loads fewer days")
    if csv_bytes > WARN_CSV_BYTES:
        log(f"      warning: {sizes}; {human_size(free)} free")


# --------------------------------------------------------------------------- #
# fetching and parsing
# --------------------------------------------------------------------------- #

def read_csv_rows(path: Path, log: Log) -> Iterator[dict[str, str]]:
    """Rows of a downloaded CSV keyed by its header; malformed rows are counted."""
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader, None)
        if header is None:
            return
        skipped = 0
        parsed = 0
        for row in reader:
            if len(row) != len(header):
                skipped += 1
                continue
            parsed += 1
            if parsed % ROW_LOG_STEP == 0:
                log(f"      parsed {parsed:,} rows")
            yield dict(zip(header, row))
        if skipped:
            log(f"      warning: skipped {skipped} malformed CSV rows")


def fetch_with_drift(conn: sqlite3.Connection, source: Source, table: Table,
                     fields: list[str], start: date, end: date, dest: Path, log: Log,
                     fresh: bool) -> list[str]:
    """Fetch into `dest`, dropping fields the source rejects; returns the fields used."""
    fields = list(fields)
    while True:
        try:
            source.fetch(table, fields, start, end, dest, log, fresh=fresh)
            return fields
        except RequestRejected as error:
            protected = (table.date_field, table.device_field)  # dating and sampling need them
            candidates = [f for f in fields if f not in protected]
            bad = [f for f in source.rejected_fields(error.text, candidates) if f in candidates]
            # An answer naming every field is not about fields (e.g. it echoes the request).
            if not bad or len(bad) == len(candidates):
                raise
            fields = [f for f in fields if f not in bad]
            store.store_fields(conn, source.name, table.name, fields, rejected=bad)
            log(f"      rejected fields {', '.join(bad)}; continuing without them")


class Prefetcher:
    """Starts preparing the next closed range while the current one downloads.

    Preparation dominates a backfill and sources like AppMetrica queue up to
    three exports per app, so warming the next range turns most of its wait
    into a download that is already done.
    """

    def __init__(self, source: Source, enabled: bool):
        self._source = source
        self._executor = ThreadPoolExecutor(max_workers=1) if enabled else None

    def warm(self, table: Table, fields: list[str], chunk: Sequence[date], fresh_edge: date) -> None:
        if self._executor is None or not chunk or chunk[-1] >= fresh_edge:
            return  # fresh ranges are rebuilt from scratch anyway; warming them is waste
        self._executor.submit(self._touch, table, list(fields), chunk[0], chunk[-1])

    def _touch(self, table: Table, fields: list[str], start: date, end: date) -> None:
        try:
            self._source.warm(table, fields, start, end)
        except Exception:  # noqa: BLE001 - the real request reports real problems
            pass

    def close(self, wait: bool = False) -> None:
        """Stop warming; a pending warm-up for a range already loaded is waste."""
        if self._executor is not None:
            self._executor.shutdown(wait=wait, cancel_futures=not wait)


# --------------------------------------------------------------------------- #
# the run
# --------------------------------------------------------------------------- #

def run(conn: sqlite3.Connection, source: Source, options: SyncOptions, *, work_dir: Path,
        log: Log = print, today: date | None = None,
        clock: Callable[[], datetime] = datetime.now) -> SyncResult:
    """Sync the chosen tables of one source into `conn` (schema must exist).

    `today` and `clock` are injectable so selftest can replay days and hours.
    """
    started = time.time()
    today = today or date.today()
    tables = resolve_tables(source, options.tables)
    if not 0 < options.sample <= 1:
        raise GakError(f"--sample must be in (0, 1], got {options.sample:g}")
    apply_settings(conn, source.name, options, log)  # before any request: a refusal is free

    for key, value in source.connect().items():
        store.set_meta(conn, f"{source.name}.{key}", value)
    log(source.check())

    since = options.since or source.first_day() or today - timedelta(days=30)
    until = options.until or today
    if since > until:
        raise GakError(f"since {since} is later than until {until}")
    days = date_range(since, until)
    fresh_edge = today - timedelta(days=options.fresh_days)
    log(f"range {since} .. {until} ({len(days)} days), tables: "
        f"{', '.join(t.name for t in tables)}")
    log(f"days since {fresh_edge} stay fresh (late delivery) and are re-pulled when older "
        f"than {options.refresh_after_hours:g}h; today {today} is always incomplete")
    log(f"sample: {describe_sample(options.sample)}; event parameters "
        + ("flattened into event_params" if options.flatten else "not flattened (--no-flatten)"))

    result = SyncResult()
    work_dir.mkdir(parents=True, exist_ok=True)
    job = _Job(conn, source, options, fresh_edge, work_dir, log, clock,
               Prefetcher(source, enabled=options.prefetch and not options.dry_run))
    try:
        for table in tables:
            result.tables.append(job.sync_table(table, days))
    finally:
        job.prefetcher.close()
    result.seconds = time.time() - started

    if options.dry_run:
        log(f"dry run: {sum(t.chunks for t in result.tables)} request(s), "
            f"{sum(t.days for t in result.tables)} day(s) would be loaded")
        return result
    store.set_meta(conn, f"{source.name}.last_sync_at", store.now_iso())
    store.checkpoint(conn)  # leave a self-contained database file behind
    per_table =", ".join(f"{t.table} {t.rows:,}" for t in result.tables)
    log(f"done: {result.rows:,} rows in {result.seconds:.0f}s ({per_table})")
    return result


@dataclass
class _Job:
    """Everything one sync run shares between its tables and chunks."""

    conn: sqlite3.Connection
    source: Source
    options: SyncOptions
    fresh_edge: date
    work_dir: Path
    log: Log
    clock: Callable[[], datetime]
    prefetcher: Prefetcher
    growth_ratio: dict[str, float] = field(default_factory=dict)  # per table, this run

    def sync_table(self, table: Table, days: list[date]) -> TableResult:
        name = self.source.name
        rejected = set() if self.options.recheck_fields else \
            store.rejected_fields(self.conn, name, table.name)
        fields = [f for f in table.requested_fields(self.options.with_device_ids)
                  if f not in rejected]
        states = store.day_states(self.conn, name, table.name)
        pending, skipped = plan_days(days, states, force=self.options.force,
                                     refresh_after_hours=self.options.refresh_after_hours,
                                     now=self.clock())
        chunks = plan_chunks(pending, self.options.chunk_days)
        summary = ", ".join(f"{count} {reason}" for reason, count in sorted(skipped.items()))
        self.log(f"== {table.name} ==  {len(chunks)} request(s), {len(pending)} day(s) to load"
                 + (f"  (skipped: {summary})" if summary else ""))
        result = TableResult(table.name, days=len(pending), chunks=len(chunks))

        for index, chunk in enumerate(chunks):
            final = chunk[-1] < self.fresh_edge
            # A cached answer is fine for closed days, but a range still inside
            # the late-delivery window - or loaded while it was - is rebuilt.
            fresh = not final or any(not states[d.isoformat()].is_final
                                     for d in chunk if d.isoformat() in states)
            span = f"{chunk[0]}..{chunk[-1]}" if len(chunk) > 1 else str(chunk[0])
            label = f"  [{index + 1}/{len(chunks)}] {span}  {len(chunk)} day(s)" + \
                ("" if final else "  (fresh window)")
            if self.options.dry_run:
                self.log(f"{label}  would be requested with {len(fields)} fields")
                continue
            self.log(label)
            if index + 1 < len(chunks):
                self.prefetcher.warm(table, fields, chunks[index + 1], self.fresh_edge)
            fields, rows = self._load_chunk(table, fields, chunk, fresh)
            result.rows += rows
        if not self.options.dry_run:
            store.store_fields(self.conn, name, table.name, fields)
        return result

    def _load_chunk(self, table: Table, fields: list[str], chunk: list[date],
                    fresh: bool) -> tuple[list[str], int]:
        started = time.time()
        start, end = chunk[0], chunk[-1]
        dest = self.work_dir / f"{self.source.name}_{table.name}.csv"
        db = store.db_file(self.conn)
        flattening = bool(table.json_field) and self.options.flatten
        count = RowCount()
        try:
            fields = fetch_with_drift(self.conn, self.source, table, fields, start, end, dest,
                                      self.log, fresh)
            downloaded = time.time()
            csv_bytes = dest.stat().st_size
            check_disk(f"{table.name} {start}..{end}", csv_bytes,
                       projected_growth(csv_bytes, self.options.sample, flattening,
                                        self.growth_ratio.get(table.name, 0.0)),
                       db.parent if db else self.work_dir, self.log)
            size_before = _size(db)
            loaded_at = self.clock()
            rows = sampled(read_csv_rows(dest, self.log), table.device_field,
                           sample_threshold(self.options.sample), count)
            with store.transaction(self.conn):
                outcome = store.replace_range(self.conn, table, fields, rows, start, end,
                                              load_date=loaded_at.date().isoformat(),
                                              flatten_params=self.options.flatten)
                for day in chunk:
                    store.mark_day(self.conn, self.source.name, table.name, day,
                                   outcome.per_day.get(day.isoformat(), 0),
                                   final=day < self.fresh_edge, loaded_at=loaded_at)
            store.checkpoint(self.conn)
        finally:
            dest.unlink(missing_ok=True)
        stored = sum(outcome.per_day.values())
        if outcome.outside:
            self.log(f"      warning: {outcome.outside:,} rows dated outside {start}..{end} "
                     "were skipped (their own day's request delivers them)")
        load_sec = time.time() - downloaded
        growth = max(0, _size(db) - size_before)
        if csv_bytes >= 1 << 20:  # a small file says more about page overhead than rows
            ratio = growth / (csv_bytes * self.options.sample)
            self.growth_ratio[table.name] = max(self.growth_ratio.get(table.name, 0.0), ratio)
        kept = "" if count.kept == count.read else f" of {count.read:,} read (sample)"
        self.log(f"      {stored:,} rows{kept} from a {human_size(csv_bytes)} CSV; download "
                 f"{downloaded - started:.0f}s, load {load_sec:.0f}s "
                 f"({count.read / max(load_sec, 0.001):,.0f} rows/s); "
                 f"database +{human_size(growth)}")
        return fields, stored


def _size(path: Path | None) -> int:
    return path.stat().st_size if path and path.exists() else 0
