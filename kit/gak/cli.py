"""Command line of the kit: `py analytics/ga.py <command>`.

Output is written for an agent reading a terminal: plain text, no colors,
compact, long listings capped with a note, a summary line at the end, and on
failure a single `error: ...` line on stderr with a non-zero exit code.
Every relative path in the config and in --db / --out is resolved against the
analytics/ folder; input files (import-csv, query path.sql) are looked up in the
current directory first, then in analytics/.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Callable, Sequence

from . import (GakError, __version__, catalog, config, csv_import, jobs, metrics, query, sequences, sources,
               store, sync)
from .http import human_size

MODEL_DIR = "model"
DEFAULT_SCAFFOLD = "model/010_v_events.sql"


def out(message: str = "") -> None:
    print(message, flush=True)


@dataclass
class Context:
    analytics_dir: Path
    argv: list[str] = field(default_factory=list)
    _config: config.Config | None = field(default=None, repr=False)

    @property
    def config(self) -> config.Config:
        if self._config is None:
            self._config = config.load(self.analytics_dir)
        return self._config

    def db_path(self, override: str | None) -> Path:
        return self.config.resolve(override) if override else self.config.db_path

    def input_file(self, name: str) -> Path:
        for candidate in (Path(name), self.analytics_dir / name):
            if candidate.is_file():
                return candidate.resolve()
        raise GakError(f"file {name} not found (looked in the current folder and analytics/)")

    def show(self, path: Path) -> str:
        """A path relative to analytics/ when inside it, for compact output."""
        try:
            return path.resolve().relative_to(self.analytics_dir).as_posix()
        except ValueError:
            return str(path)


# --------------------------------------------------------------------------- #
# status / apps / sync
# --------------------------------------------------------------------------- #

def cmd_status(ctx: Context, args: argparse.Namespace) -> int:
    cfg = ctx.config
    out(f"game-analytics-kit {__version__} (python {sys.version.split()[0]}, "
        f"sqlite {sqlite3.sqlite_version}), analytics dir {ctx.analytics_dir}")
    out(f"config: {cfg.path.name}" + ("" if cfg.exists else " not found, using defaults")
        + f"; project {cfg.project_name or '(unnamed)'}, report language {cfg.report_language}")
    for name in cfg.sources:
        _status_source(ctx, name)
    db = ctx.db_path(args.db)
    job = jobs.describe(db.parent)
    if job:
        out(job)
    if not db.exists():
        out(f"database: {ctx.show(db)} not created yet; run `ga.py sync`")
        return 0
    out(f"database: {ctx.show(db)} ({human_size(db.stat().st_size)})")
    conn = store.connect_readonly(db)
    try:
        _status_tables(ctx, conn)
    finally:
        conn.close()
    return 0


def _status_source(ctx: Context, name: str) -> None:
    options = ctx.config.source(name)
    tables = options["tables"]
    tables_text = "default set" if tables is None else (tables if isinstance(tables, str)
                                                         else ", ".join(tables))
    out(f"source {name}: {'enabled' if options['enabled'] else 'disabled'}; "
        f"api_key {options['api_key'] or 'not set'}; app_id {options['app_id'] or 'auto'}; "
        f"since {options['since'] or 'app creation'}; tables {tables_text}; "
        f"sample {options['sample']:g}; flatten_params {str(options['flatten_params']).lower()}")
    if name not in sources.REGISTRY:
        out(f"  warning: the kit has no source '{name}' (known: {', '.join(sources.REGISTRY)})")
        return
    env = sources.source_class(name).token_env
    token, origin = config.find_token(ctx.analytics_dir, env)
    out(f"  token {env}: " + (f"found in {origin}" if token else
                              "not found (environment, analytics/.env, "
                              "~/.config/game-analytics-kit/.env)"))


def _status_tables(ctx: Context, conn: sqlite3.Connection) -> None:
    tables = store.list_tables(conn)
    for name in sources.REGISTRY:
        if "meta" not in tables:
            break
        app = store.get_meta(conn, f"{name}.app_id")
        if app:
            out(f"  {name} app {app} \"{store.get_meta(conn, f'{name}.app_name') or '?'}\", "
                f"time zone {store.get_meta(conn, f'{name}.timezone') or '?'}, last sync "
                f"{store.get_meta(conn, f'{name}.last_sync_at') or 'never'}")
        rate = store.get_meta(conn, f"{name}.sample_rate")
        if rate and sync.sample_threshold(float(rate)) < sync.SAMPLE_BUCKETS:
            out(f"  sample: {sync.describe_sample(float(rate))}")
        if store.get_meta(conn, f"{name}.flatten_params") == "0":
            out("  params: not flattened (event_params empty); catalog and scaffold read "
                "event_json of recent events")
    fresh = _fresh_days(conn) if "sync_log" in tables else {}
    source_tables = [t.name for t in sources.schema_tables()]
    listed = [t for t in source_tables if t in tables] + \
        [t for t in ("event_params",) if t in tables] + \
        [t for t in tables if t.startswith("ext_")]
    out(f"{'table':<20} {'rows':>12}  {'from':<10}  {'to':<10}  notes")
    for name in listed:
        columns = store.table_columns(conn, name)
        rows = conn.execute(f"SELECT COUNT(*) FROM {store.quote(name)}").fetchone()[0]
        first = last = ""
        if "date" in columns and name in source_tables:
            first, last = conn.execute(
                f"SELECT MIN(date), MAX(date) FROM {store.quote(name)}").fetchone()
        note = f"{fresh[name]} day(s) in the fresh window" if fresh.get(name) else ""
        out(f"{name:<20} {rows:>12,}  {first or '':<10}  {last or '':<10}  {note}".rstrip())
    if "source_fields" in tables:
        for row in conn.execute("SELECT source, table_name, rejected FROM source_fields "
                                "WHERE rejected <> '' ORDER BY 1, 2"):
            out(f"rejected by {row[0]} in {row[1]}: {row[2]} (sync --recheck-fields asks again)")
    if "imports" in tables:
        count = conn.execute("SELECT COUNT(*) FROM imports").fetchone()[0]
        if count:
            out(f"imports: {count} file(s); see `ga.py sql \"SELECT * FROM imports\"`")
    views = store.list_tables(conn, "view")
    out(f"views: {', '.join(views) if views else 'none'}")
    model = sorted(p.name for p in (ctx.analytics_dir / MODEL_DIR).glob("*.sql"))
    out(f"model: {len(model)} file(s) in model/" + (f" ({', '.join(model[:6])}"
                                                    f"{', ...' if len(model) > 6 else ''})"
                                                    if model else ""))
    options = ctx.config.source(config.DEFAULT_SOURCE)
    edge = date.today() - timedelta(days=int(options["fresh_days"]))
    out(f"fresh window: days since {edge} are re-pulled when older than "
        f"{options['refresh_after_hours']:g}h; today {date.today()} is always incomplete")


def _fresh_days(conn: sqlite3.Connection) -> dict[str, int]:
    return {row[0]: row[1] for row in conn.execute(
        "SELECT table_name, SUM(is_final = 0) FROM sync_log GROUP BY table_name")}


def _make_source(ctx: Context, name: str) -> sources.Source:
    cls = sources.source_class(name)
    token, origin = config.find_token(ctx.analytics_dir, cls.token_env)
    return sources.create(name, ctx.config.source(name), token, origin, log=out)


def cmd_apps(ctx: Context, args: argparse.Namespace) -> int:
    source = _make_source(ctx, args.source)
    apps = source.applications()
    if not apps:
        raise GakError(f"the {args.source} token sees no applications; was it issued by the "
                       "account that owns the app?")
    options = ctx.config.source(args.source)
    rows = []
    for app in apps:
        mine = (options["app_id"] and app["id"] == str(options["app_id"])) or \
            (options["api_key"] and app["api_key"] == options["api_key"])
        rows.append((app["id"], app["name"], app["api_key"], app["created"], app["timezone"],
                     "<- analytics.toml" if mine else ""))
    query.render(query.Result(["id", "name", "api_key", "created", "timezone", ""], rows),
                 "table", sys.stdout)
    out(f"{len(apps)} application(s) visible to the {args.source} token")
    return 0


JOB_FLAGS = ("--background", "--wait")


def cmd_sync(ctx: Context, args: argparse.Namespace) -> int:
    data_dir = ctx.db_path(args.db).parent
    if args.background:
        child = _strip_job_flags(ctx.argv)
        jobs.start(ctx.analytics_dir / "ga.py", data_dir, child, out)
        return jobs.wait(data_dir, args.timeout, out) if args.wait else 0
    if args.wait:
        return jobs.wait(data_dir, args.timeout, out)
    jobs.ensure_idle(data_dir)
    in_job = bool(os.environ.get(jobs.ENV_STATE))
    try:
        _run_sync(ctx, args)
    except BaseException:
        if in_job:
            jobs.finish(1)
        raise
    if in_job:
        jobs.finish(0)
    return 0


def _strip_job_flags(argv: list[str]) -> list[str]:
    child, skip = [], False
    for item in argv:
        if skip:
            skip = False
            continue
        if item in JOB_FLAGS:
            continue
        if item == "--timeout":
            skip = True
            continue
        if item.startswith("--timeout="):
            continue
        child.append(item)
    return child


def _run_sync(ctx: Context, args: argparse.Namespace) -> None:
    cfg = ctx.config
    names = [args.source] if args.source else \
        [n for n in cfg.sources if cfg.source(n)["enabled"]]
    if not names:
        raise GakError("no enabled source in analytics.toml")
    db = ctx.db_path(args.db)
    conn = store.connect(db)
    try:
        store.ensure_schema(conn, sources.schema_tables())
        for name in names:
            options = _sync_options(args, cfg.source(name))
            source = _make_source(ctx, name)
            out(f"db: {ctx.show(db)}")
            sync.run(conn, source, options, work_dir=db.parent / "tmp", log=out)
    finally:
        conn.close()


def _sync_options(args: argparse.Namespace, options: dict) -> sync.SyncOptions:
    def pick(value, key):
        return options[key] if value is None else value

    since = args.since or options["since"]
    return sync.SyncOptions(
        tables=args.tables if args.tables else options["tables"],
        since=config.parse_date(since, "since") if since else None,
        until=config.parse_date(args.until, "--until") if args.until else None,
        chunk_days=int(pick(args.chunk_days, "chunk_days")),
        fresh_days=int(pick(args.fresh_days, "fresh_days")),
        refresh_after_hours=float(pick(args.refresh_after, "refresh_after_hours")),
        force=args.force,
        dry_run=args.dry_run,
        prefetch=not args.no_prefetch,
        with_device_ids=args.with_device_ids,
        recheck_fields=args.recheck_fields,
        sample=float(pick(args.sample, "sample")),
        flatten=bool(options["flatten_params"]) and not args.no_flatten,
    )


# --------------------------------------------------------------------------- #
# catalog / model
# --------------------------------------------------------------------------- #

def cmd_catalog(ctx: Context, args: argparse.Namespace) -> int:
    since = config.parse_date(args.since, "--since") if args.since else None
    conn = store.connect_readonly(ctx.db_path(args.db))
    try:
        rows, note = catalog.catalog(conn, since, args.min_count, args.max_events)
    finally:
        conn.close()
    if args.format == "json":
        records = [{"event_name": r.event_name, "events": r.events, "key": r.key,
                    "occurrences": r.occurrences, "devices": r.devices,
                    "distinct_values": r.distinct_values, "numeric_share": r.numeric_share,
                    "samples": r.samples} for r in rows]
        out(json.dumps(records, ensure_ascii=False, indent=1))
        if note:  # stdout stays pure JSON
            print(f"note: {note}", file=sys.stderr)
        return 0
    table = catalog.catalog_table(rows)
    limit = args.limit if args.limit is not None else (500 if args.format == "table" else None)
    shown = table if limit is None else table[:limit]
    query.render(query.Result(catalog.CATALOG_COLUMNS, shown, truncated=len(shown) < len(table)),
                 args.format, sys.stdout)
    events = len({r.event_name for r in rows})
    out(f"catalog: {events} event name(s), {sum(1 for r in rows if r.key)} event x key pair(s)"
        + (f" since {since}" if since else ""))
    if note:
        out(f"note: {note}")
    return 0


def cmd_model_scaffold(ctx: Context, args: argparse.Namespace) -> int:
    target = ctx.config.resolve(args.out)
    if target.exists() and not args.force:
        raise GakError(f"{ctx.show(target)} exists and belongs to the project now; edit it, "
                       "or pass --force to overwrite")
    since = config.parse_date(args.since, "--since") if args.since else None
    conn = store.connect_readonly(ctx.db_path(args.db))
    try:
        result = catalog.scaffold(conn, since=since, min_share=args.min_share, top=args.top,
                                  generated_on=date.today(), max_events=args.max_events)
    finally:
        conn.close()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(result.sql, encoding="utf-8", newline="\n")
    out(f"wrote {ctx.show(target)}: {result.columns} parameter column(s) from {result.keys} "
        f"key(s) over {result.events:,} events; edit it, then run `ga.py model apply`")
    if result.note:
        out(f"note: {result.note}")
    return 0


def cmd_model_apply(ctx: Context, args: argparse.Namespace) -> int:
    folder = ctx.analytics_dir / MODEL_DIR
    files = sorted(folder.glob("*.sql"), key=lambda p: p.name)
    if not files:
        raise GakError("no .sql files in model/; start with `ga.py model scaffold`")
    db = ctx.db_path(args.db)
    conn = store.connect(db)
    try:
        store.ensure_schema(conn, sources.schema_tables())
        count = store.apply_sql_files(conn, files)
        views = store.list_tables(conn, "view")
    finally:
        conn.close()
    out(f"applied {len(files)} file(s), {count} statement(s): {', '.join(p.name for p in files)}")
    out(f"views now: {', '.join(views)}")
    return 0


# --------------------------------------------------------------------------- #
# query / sql
# --------------------------------------------------------------------------- #

def cmd_query(ctx: Context, args: argparse.Namespace) -> int:
    if args.name == "list":
        return _query_list(ctx)
    path = query.resolve(ctx.analytics_dir, args.name)
    conn = store.connect_readonly(ctx.db_path(args.db))
    try:
        result = query.run_named(conn, path, query.parse_params(args.param),
                                 query.display_limit(args.format, args.limit))
    finally:
        conn.close()
    query.render(result, args.format, sys.stdout)
    return 0


def _query_list(ctx: Context) -> int:
    found = query.list_queries(ctx.analytics_dir)
    width = max((len(q.name) for q in found), default=10)
    for origin, folder in (("project", "analytics/queries"), ("kit", "analytics/kit/gak/queries")):
        items = [q for q in found if q.origin == origin]
        out(f"{origin} queries ({folder}): {len(items) or 'none'}")
        for item in items:
            suffix = "  (overrides the kit query)" if item.overrides else ""
            out(f"  {item.name:<{width}}  {item.title}{suffix}")
    return 0


def cmd_sql(ctx: Context, args: argparse.Namespace) -> int:
    conn = store.connect_readonly(ctx.db_path(args.db))
    try:
        result = query.execute(conn, args.statement, query.parse_params(args.param),
                               query.display_limit(args.format, args.limit))
    finally:
        conn.close()
    query.render(result, args.format, sys.stdout)
    return 0


# --------------------------------------------------------------------------- #
# keymetrics / dropoff
# --------------------------------------------------------------------------- #

def _dates(args: argparse.Namespace) -> tuple[str | None, str | None]:
    since = config.parse_date(args.since, "--since").isoformat() if args.since else None
    until = config.parse_date(args.until, "--until").isoformat() if args.until else None
    return since, until


def _emit(ctx: Context, text: str, target: str | None, what: str) -> None:
    """Print the rendered table, or write it to --out (relative to analytics/)."""
    if not target:
        sys.stdout.write(text if text.endswith("\n") else text + "\n")
        return
    given = Path(target)
    # From the project root people write analytics/reports/...: accept it as well.
    path = (ctx.analytics_dir.parent / given if not given.is_absolute() and given.parts
            and given.parts[0] == ctx.analytics_dir.name else ctx.config.resolve(target))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    out(f"wrote {ctx.show(path)} ({what})")


def cmd_keymetrics(ctx: Context, args: argparse.Namespace) -> int:
    since, until = _dates(args)
    conn = store.connect_readonly(ctx.db_path(args.db))
    try:
        result = metrics.key_metrics(conn, by=args.by, top=args.top, players=args.players, since=since,
                                     until=until, life_days=args.life_days, cap=args.cap,
                                     min_devices=args.min_devices)
    finally:
        conn.close()
    _emit(ctx, metrics.render_key_metrics(result, args.format, ctx.config.report_language), args.out,
          f"key metrics, {len(result.population.devices):,} devices, {args.format}")
    if args.out and args.format != "table":
        out(metrics._km_footer(result).rstrip())
    return 0


def cmd_dropoff(ctx: Context, args: argparse.Namespace) -> int:
    since, until = _dates(args)
    conn = store.connect_readonly(ctx.db_path(args.db))
    try:
        result = metrics.dropoff(conn, players=args.players, steps=args.steps, since=since, until=until,
                                 version=args.version, country=args.country, step_sec=args.step_sec,
                                 max_sec=args.max_sec, scope=args.scope, cap=args.cap)
    finally:
        conn.close()
    lang = ctx.config.report_language
    _emit(ctx, metrics.render_dropoff(result, args.format, lang), args.out,
          f"drop-off, {len(result.population.devices):,} devices, {args.format}")
    if args.svg:
        _emit(ctx, metrics.dropoff_svg(result, lang), args.svg, "drop-off chart")
    return 0


def cmd_ordinals(ctx: Context, args: argparse.Namespace) -> int:
    since, until = _dates(args)
    conn = store.connect_readonly(ctx.db_path(args.db))
    try:
        result = sequences.ordinals(conn, events=args.events, actions=args.actions, players=args.players,
                                    since=since, until=until, max_n=args.max_n)
    finally:
        conn.close()
    _emit(ctx, sequences.render_ordinals(result, args.format, ctx.config.report_language), args.out,
          f"actions by ordinal, {len(result.population.devices):,} devices, {args.format}")
    return 0


def cmd_leaving(ctx: Context, args: argparse.Namespace) -> int:
    since, until = _dates(args)
    conn = store.connect_readonly(ctx.db_path(args.db))
    try:
        result = sequences.leaving(conn, events=args.events, triggers=args.triggers, pause_events=args.pause,
                                   resume_events=args.resume, ignore=args.ignore, window=args.window,
                                   players=args.players, since=since, until=until)
    finally:
        conn.close()
    _emit(ctx, sequences.render_leaving(result, args.format, ctx.config.report_language), args.out,
          f"leaving after events, {len(result.population.devices):,} devices, {args.format}")
    return 0


# --------------------------------------------------------------------------- #
# import-csv / report / selftest
# --------------------------------------------------------------------------- #

def cmd_import_csv(ctx: Context, args: argparse.Namespace) -> int:
    path = ctx.input_file(args.file)
    conn = store.connect(ctx.db_path(args.db))
    try:
        store.ensure_schema(conn, sources.schema_tables())
        result = csv_import.import_csv(conn, path, kind=args.kind, table=args.table,
                                       replace=args.replace, display_name=ctx.show(path))
    finally:
        conn.close()
    out(f"file: {ctx.show(path)} ({result.encoding}, delimiter {result.delimiter}, kind {args.kind})")
    for line in result.preamble:
        out(f"preamble: {line}")
    for note in result.skipped:
        out(f"note: {note}")
    columns = ", ".join(c + ("(+num)" if c in result.numeric_columns else "")
                        for c in result.columns)
    out(f"columns: {columns}")
    out(f"imported {result.rows:,} row(s) into {result.table} (import id {result.import_id})")
    return 0


def cmd_report(ctx: Context, args: argparse.Namespace) -> int:
    try:
        from .report import builder
    except ImportError as error:
        raise GakError(f"the report package is missing or broken ({error}); "
                       "reinstall the kit") from None
    try:
        if args.report_command == "new":
            path = builder.new_version(ctx.analytics_dir, args.slug, args.title,
                                       _version_number(args.from_version), kind=args.kind)
        elif args.report_command == "build":
            path = builder.build(ctx.analytics_dir, args.slug, _version_number(args.version),
                                 force=args.force)
        else:
            path = builder.build_index(ctx.analytics_dir)
    except builder.ReportError as error:
        raise GakError(str(error)) from None
    out(str(path))
    return 0


def _version_number(value: str | None) -> int | None:
    if value is None:
        return None
    text = value.strip().lower().lstrip("v")
    if not text.isdigit() or int(text) < 1:
        raise GakError(f"bad version '{value}': use a number like 2 or v002")
    return int(text)


def cmd_selftest(ctx: Context, args: argparse.Namespace) -> int:
    script = Path(__file__).resolve().parent.parent / "selftest.py"
    if not script.is_file():
        raise GakError(f"{script} is missing; reinstall the kit")
    spec = importlib.util.spec_from_file_location("gak_selftest", script)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up while it loads
    spec.loader.exec_module(module)
    return module.main()


# --------------------------------------------------------------------------- #
# parser
# --------------------------------------------------------------------------- #

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ga.py", description="game-analytics-kit: raw analytics -> SQLite -> reports")
    parser.add_argument("--version", action="version", version=f"game-analytics-kit {__version__}")
    db = argparse.ArgumentParser(add_help=False)
    db.add_argument("--db", help="SQLite file, relative to analytics/ (default from analytics.toml)")
    formats = argparse.ArgumentParser(add_help=False)
    formats.add_argument("--format", choices=query.FORMATS, default="table")
    formats.add_argument("--limit", type=int, help="max rows (table format defaults to "
                                                   f"{query.TABLE_ROW_CAP})")
    formats.add_argument("--param", "-p", action="append", default=[], metavar="NAME=VALUE",
                         help="bind :NAME (repeatable); :since/:until/:limit have defaults")
    sub = parser.add_subparsers(dest="command", required=True, metavar="<command>")

    def command(name: str, handler: Callable, help_text: str,
                parents: Sequence[argparse.ArgumentParser] = ()) -> argparse.ArgumentParser:
        item = sub.add_parser(name, help=help_text, description=help_text, parents=list(parents))
        item.set_defaults(handler=handler)
        return item

    command("status", cmd_status, "kit, config, token, database and sync state", [db])

    apps = command("apps", cmd_apps, "applications the source token can see")
    apps.add_argument("--source", default=config.DEFAULT_SOURCE, choices=list(sources.REGISTRY))

    sync_cmd = command("sync", cmd_sync, "pull raw data into SQLite (idempotent)", [db])
    sync_cmd.add_argument("--source", choices=list(sources.REGISTRY),
                          help="default: every enabled source in analytics.toml")
    sync_cmd.add_argument("--tables", help="comma separated names, or 'all' (default: config)")
    sync_cmd.add_argument("--since", help="first day YYYY-MM-DD (default: config, else app creation)")
    sync_cmd.add_argument("--until", help="last day YYYY-MM-DD (default: today)")
    sync_cmd.add_argument("--chunk-days", type=int, help="days per request (default 7): exports "
                          "are prepared one by one, so bigger ranges are faster")
    sync_cmd.add_argument("--fresh-days", type=int, help="days still receiving late events (default 7)")
    sync_cmd.add_argument("--refresh-after", type=float, metavar="HOURS",
                          help="re-request a fresh day only when its last load is older "
                               "(default 12; 0 = every run)")
    sync_cmd.add_argument("--force", action="store_true", help="re-request final days too")
    sync_cmd.add_argument("--dry-run", action="store_true", help="print the plan, load nothing")
    sync_cmd.add_argument("--no-prefetch", action="store_true",
                          help="do not warm up the next range while loading the current one")
    sync_cmd.add_argument("--with-device-ids", action="store_true",
                          help="also request advertising ids, IP and operator (personal data)")
    sync_cmd.add_argument("--background", action="store_true",
                          help="run the sync as a detached process that outlives this shell; "
                               "log in data/sync.log")
    sync_cmd.add_argument("--wait", action="store_true",
                          help="follow the background sync until it ends (exit 3 = still running)")
    sync_cmd.add_argument("--timeout", type=float, default=90,
                          help="seconds --wait follows the job before returning (default 90, "
                               "well below the per-command time limit of agents; exit 3 = call again)")
    sync_cmd.add_argument("--recheck-fields", action="store_true",
                          help="request fields the API rejected before once more")
    sync_cmd.add_argument("--sample", type=float, metavar="R",
                          help="keep this share of devices, 0 < R <= 1 (default: config, 1.0); "
                               "fixed per database: the first sync sets it")
    sync_cmd.add_argument("--no-flatten", action="store_true",
                          help="do not write event_params (the largest part of the database); "
                               "catalog and scaffold then read event_json")

    cat = command("catalog", cmd_catalog, "event names x parameter keys with sample values", [db])
    cat.add_argument("--since", help="only events since YYYY-MM-DD")
    cat.add_argument("--min-count", type=int, default=1, help="hide pairs seen fewer times")
    cat.add_argument("--format", choices=("table", "md", "json"), default="table")
    cat.add_argument("--limit", type=int, help="max rows (table format defaults to 500)")
    cat.add_argument("--max-events", type=int, default=catalog.MAX_EVENTS,
                     help="without event_params: how many of the latest events to read "
                          f"from event_json (default {catalog.MAX_EVENTS:,})")

    model = command("model", None, "project model: scaffold v_events, apply model/*.sql")
    model_sub = model.add_subparsers(dest="model_command", required=True, metavar="<action>")
    scaffold = model_sub.add_parser("scaffold", parents=[db],
                                    help="write model/010_v_events.sql from the catalog")
    scaffold.set_defaults(handler=cmd_model_scaffold)
    scaffold.add_argument("--out", default=DEFAULT_SCAFFOLD, help="relative to analytics/")
    scaffold.add_argument("--min-share", type=float, default=0.1,
                          help="keep a key present in at least this share of some event's rows")
    scaffold.add_argument("--top", type=int, default=0,
                          help="also keep the N most frequent keys whatever their share")
    scaffold.add_argument("--since", help="only look at events since YYYY-MM-DD")
    scaffold.add_argument("--max-events", type=int, default=catalog.MAX_EVENTS,
                          help="without event_params: how many of the latest events to read "
                               f"from event_json (default {catalog.MAX_EVENTS:,})")
    scaffold.add_argument("--force", action="store_true", help="overwrite an existing file")
    apply_cmd = model_sub.add_parser("apply", parents=[db],
                                     help="run model/*.sql in name order in one transaction")
    apply_cmd.set_defaults(handler=cmd_model_apply)

    q = command("query", cmd_query, "run a named query (`query list` shows them)", [db, formats])
    q.add_argument("name", help="query name, path to a .sql file, or 'list'")

    sql_cmd = command("sql", cmd_sql, "ad-hoc read-only SQL", [db, formats])
    sql_cmd.add_argument("statement", help="one SQL statement")

    imp = command("import-csv", cmd_import_csv, "load a console CSV export into ext_<table>", [db])
    imp.add_argument("file", help="CSV file (current folder first, then analytics/)")
    imp.add_argument("--kind", choices=csv_import.KINDS, default="generic")
    imp.add_argument("--table", help="table name without ext_ (default: from the file name)")
    imp.add_argument("--replace", action="store_true",
                     help="drop and rebuild the table; allows importing the same file again")

    population = argparse.ArgumentParser(add_help=False)
    population.add_argument("--since", help="first day of first events (cohort), YYYY-MM-DD")
    population.add_argument("--until", help="last day of first events (cohort), YYYY-MM-DD")
    population.add_argument("--players", metavar="VIEW|SELECT",
                            help="population: a view/table with device_id or a SELECT returning it "
                                 "(default v_players when the model has it)")
    population.add_argument("--cap", type=int, default=metrics.DEFAULT_CAP, metavar="SEC",
                            help="largest gap between two events that counts as play (default 600)")
    population.add_argument("--format", choices=metrics.FORMATS, default="table",
                            help="html = a ready .tablebox fragment in the report language")
    population.add_argument("--out", metavar="FILE", help="write the output here (relative to analytics/), "
                            "e.g. reports/<slug>/v001/assets/keymetrics.html")

    km = command("keymetrics", cmd_keymetrics, "key-metrics table by first version / country", [db, population])
    km.add_argument("--by", choices=("version", "country", "none"), default="version",
                    help="columns: cohort groups by first version (default), first country, or none")
    km.add_argument("--top", type=int, default=6, help="largest groups shown as columns (default 6)")
    km.add_argument("--life-days", type=int, metavar="N",
                    help="count activity of life days 0..N-1 only (default: everything loaded)")
    km.add_argument("--min-devices", type=int, default=10,
                    help="a group with fewer devices gets no column of its own (default 10)")

    drop = command("dropoff", cmd_dropoff, "drop-off table: ordered steps, then active-time buckets",
                   [db, population])
    drop.add_argument("--steps", metavar="VIEW|SELECT",
                      help="rows device_id, step_no, step_name (loading and FTUE steps)")
    drop.add_argument("--version", help="only devices whose first version is this")
    drop.add_argument("--country", help="only devices whose first country is this (ISO code)")
    drop.add_argument("--step-sec", type=int, default=30, help="bucket size in seconds (default 30)")
    drop.add_argument("--max-sec", type=int, default=600, help="last bucket in seconds (default 600)")
    drop.add_argument("--scope", choices=("all", "first-day", "first-session"), default="all",
                      help="which activity counts as active time (default all)")
    drop.add_argument("--svg", metavar="FILE", help="also write the chart (relative to analytics/)")

    population_no_cap = argparse.ArgumentParser(add_help=False)
    for action in population._actions:
        if action.dest not in ("help", "cap"):
            population_no_cap._add_action(action)
    orders = command("ordinals", cmd_ordinals, "core actions by their number within a session",
                     [db, population_no_cap])
    orders.add_argument("--events", help="event names, comma separated")
    orders.add_argument("--actions", metavar="VIEW|SELECT",
                        help="rows device_id, session_id, ts, label [, sec]: parameter-level actions or the "
                             "project's own session unit; sec = seconds into the session")
    orders.add_argument("--max-n", type=int, default=sequences.MAX_N, help="largest ordinal shown (default 15)")

    leave = command("leaving", cmd_leaving, "what players do right after an event: background, stop, never return",
                    [db, population_no_cap])
    leave.add_argument("--events", help="trigger event names, comma separated (add a neutral one to compare)")
    leave.add_argument("--triggers", metavar="VIEW|SELECT", help="rows device_id, ts, label")
    leave.add_argument("--pause", metavar="EVENTS|VIEW|SELECT",
                       help="event names the game sends when the app goes to the background, or rows "
                            "device_id, ts when it is one event with a flag")
    leave.add_argument("--resume", metavar="EVENTS|VIEW|SELECT",
                       help="the same for the return to the foreground (default: any event after the pause)")
    leave.add_argument("--ignore", metavar="EVENTS",
                       help="events that are not the player acting (heartbeats, focus/pause events)")
    leave.add_argument("--window", type=int, default=sequences.WINDOW, help="seconds after the event (default 20)")

    report = command("report", cmd_report, "versioned HTML reports")
    report_sub = report.add_subparsers(dest="report_command", required=True, metavar="<action>")
    new = report_sub.add_parser("new", help="create the next version folder of a report")
    new.add_argument("slug")
    new.add_argument("--title", required=True, help="the request: game, version, period and what was asked")
    new.add_argument("--kind", choices=("full", "question"),
                     help="full review (all seven blocks) or one question (default: question, "
                          "or the kind of the --from version)")
    new.add_argument("--from", dest="from_version", help="copy the body from version vN")
    build = report_sub.add_parser("build", help="build report.html and artifact.html")
    build.add_argument("slug")
    build.add_argument("--version", help="version number (default: latest)")
    build.add_argument("--force", action="store_true", help="rebuild a built version (repair only)")
    report_sub.add_parser("index", help="rebuild reports/index.html")

    command("selftest", cmd_selftest, "offline tests of the kit on synthetic data")
    return parser


def _utf8_output() -> None:
    """Russian text must not crash a Windows console or pipe with a legacy code page."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def main(argv: Sequence[str] | None = None, analytics_dir: Path | None = None) -> int:
    _utf8_output()
    if sys.version_info < (3, 11):
        print("error: game-analytics-kit needs Python 3.11 or newer", file=sys.stderr)
        return 2
    ctx = Context(Path(analytics_dir or Path.cwd()).resolve(), argv=list(argv if argv is not None else sys.argv[1:]))
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as exit_:
        return exit_.code if isinstance(exit_.code, int) else 2
    if Path.cwd().resolve() == ctx.analytics_dir:
        # Agents that `cd analytics` then search the game code with root-relative paths and fail.
        print("note: run ga.py from the project root (`py analytics/ga.py ...`), not from analytics/",
              file=sys.stderr)
    try:
        return int(args.handler(ctx, args) or 0)
    except GakError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("error: interrupted", file=sys.stderr)
        return 130
    except Exception as error:  # noqa: BLE001 - one line for the agent, traceback on demand
        if os.environ.get("GAK_DEBUG"):
            raise
        print(f"error: {type(error).__name__}: {error} (set GAK_DEBUG=1 for the traceback)",
              file=sys.stderr)
        return 1
