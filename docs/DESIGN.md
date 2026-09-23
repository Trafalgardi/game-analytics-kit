# game-analytics-kit — design

A portable kit that gives a coding agent (Claude Code or OpenAI Codex) everything it needs
to pull a game's raw analytics into a local SQLite database, model it for *this* project,
research product questions and publish versioned, self-contained HTML reports.

The kit is installed **into** a game project by `install.py`. Nothing here is specific to one
game; everything game-specific (event names, parameters, cohorts, queries, notes) is written
by the agent inside the target project, guided by the skills.

This document is the contract every part of the kit follows. Change it first, then the code.

---

## 1. Repository layout (this repo)

```
game-analytics-kit/
  README.md / README.ru.md  English / Russian: what it is, quick start, usage with Claude and Codex
  CONTRIBUTING.md         tests, skill rules, commit format
  SECURITY.md             what happens to the token, how to report a vulnerability
  LICENSE                 MIT
  CHANGELOG.md
  VERSION                 semver, e.g. 0.1.0
  AGENTS.md / CLAUDE.md   rules for agents that develop the kit itself
  .github/ISSUE_TEMPLATE/ bug report and skill feedback forms
  .github/workflows/      ci.yml (tests on Linux, macOS, Windows), pages.yml (the site)
  site/                   GitHub Pages landing (EN, ru/); the workflow adds docs/images and
                          the example reports under examples/
  install.py              install / update / uninstall into a target project (stdlib only)
  kit/                    the engine; copied to <project>/analytics/kit/ on install
    gak/                  python package "gak" (game analytics kit), stdlib only
      __init__.py         __version__
      cli.py              argparse entry point for every command in section 4
      config.py           analytics.toml + secrets loading
      store.py            SQLite connection, core schema, range replace, sync_log, meta
      flatten.py          event_json -> event_params rows
      http.py             download with retries, 202 polling, 429 Retry-After, gzip, temp file
      sync.py             generic planner: chunking, fresh window, refresh-after, prefetch
      catalog.py          event catalog + v_events scaffold generator
      query.py            run .sql files with :params, render table/md/csv/json
      csv_import.py       generic CSV importer for console exports (Google Ads, AdMob, GA4, Play)
      metrics.py          standard tables of a full review: key metrics by cohort group, drop-off
      sequences.py        standard tables from event sequences: actions by ordinal, leaving after events
      sources/
        __init__.py       registry: name -> Source class
        base.py           Source interface (section 3)
        appmetrica.py     AppMetrica Logs API + Management API
        appmetrica_fields.py  per-table field lists and column types
      queries/            generic SQL that only touches core tables (section 5)
      report/
        __init__.py
        builder.py        versioned reports: new / build / index (section 6)
        charts.py         SVG chart helpers using theme-token CSS classes
        theme.css         the one stylesheet every report embeds (light + dark)
        shell.html        standalone wrapper (doctype, fonts, <style>{{css}}</style>)
        index.html        template for reports/index.html
        scaffold_full.html      starting body of a full review (all seven blocks, section 6)
        scaffold_question.html  starting body of a question report (blocks 1, 6, 7 + needed of 2-5)
      schema_core.sql     core tables and generic views
    selftest.py           offline tests with synthetic data (no network)
  templates/              copied into <project>/analytics/ only when absent
    analytics.toml
    env.example
    gitignore             becomes analytics/.gitignore
    ga.py                 launcher: puts kit/ on sys.path and calls gak.cli.main
    notes/project.md      skeleton of the project knowledge file
    notes/findings.md     skeleton of the dated findings log
    model/README.md
    queries/README.md
  skills/                 copied into <project>/.claude/skills/ AND <project>/.agents/skills/
    analytics-kit/
    analytics-connect-appmetrica/
    analytics-data-model/
    analytics-project-audit/
    analytics-import-external/
    analytics-research/
    analytics-report/
  docs/
    DESIGN.md             this file
    KNOWLEDGE.md          field experience the skills are written from
    TESTING.md / TEST_LOG.md  how the kit is tested end to end, and the runs so far
    examples/sample-report/   generated example reports (full review + question) on made-up data
    images/               screenshots for the README and the site, social-preview.png (+ its .html source)
  tests/                  test helpers for install.py (optional)
```

## 2. What a project looks like after install

```
<project root>/                 git root of the game project
  .claude/skills/analytics-*    copies of skills/ (Claude Code discovers them here)
  .agents/skills/analytics-*    the same copies (OpenAI Codex discovers them here)
  analytics/                    never inside a Unity Assets/ folder
    ga.py                       launcher — every command is `py analytics/ga.py <cmd>`
    analytics.toml              project config (committed)
    .env                        secrets (git-ignored); see config order below
    .gitignore                  ignores data/, .env, imports/, reports/**/work/
    kit/                        engine, managed by install.py — do not edit in the project
      VERSION
      gak/...
    data/analytics.db           SQLite (git-ignored)
    model/                      project SQL: views and tables built on top of core tables
      010_v_events.sql          ... applied in file-name order by `ga.py model apply`
    queries/                    project queries, one .sql per question, header comment = title
    imports/                    CSV exports and screenshots the owner drops in
    notes/
      project.md                durable facts about this project's data (SDK keys, event meaning,
                                dev devices, attribution quirks). Read before any work.
      findings.md               dated log of research conclusions, newest first
    reports/
      index.html                generated list of all reports and versions
      <slug>/v001/              one version = one folder, never rewritten after build
        report.src.html         body fragment the agent writes (placeholders allowed)
        report.md               short summary for chat / messengers (optional, recommended)
        assets/                 svg charts, png screenshots
        work/                   scripts and scratch the agent used (git-ignored)
        meta.json
        report.html             built, standalone, self-contained (open from disk)
        artifact.html           built, same content without <html>/<head>/<body> (for Claude Artifacts)
```

Windows is first class: paths with backslashes, `py` launcher, no symlinks required.
Commands are written as `py analytics/ga.py ...`; on macOS/Linux the agent uses `python3`.

### Config: `analytics/analytics.toml`

```toml
[project]
name = "My Game"
report_language = "ru"          # language of reports; skills themselves are English
platforms = ["android"]

[database]
path = "data/analytics.db"      # relative to analytics/

[sources.appmetrica]
enabled = true
api_key = ""                    # SDK key found in the game code; resolves the numeric app id
app_id = ""                     # optional numeric id; wins over api_key when set
since = ""                      # first day to pull, YYYY-MM-DD; empty = app creation date
tables = ["events", "sessions_starts", "installations"]   # default set; "all" in CLI adds the rest
chunk_days = 7
fresh_days = 7
refresh_after_hours = 12
sample = 1.0                    # share of devices kept, 0 < r <= 1, deterministic by device id;
                                # fixed per database by its first sync (0.1 for a big game)
flatten_params = true           # write event_params; false for a big game: at 20-30 params per
                                # event it is most of the database (catalog/scaffold then sample event_json)

[filters]                       # used by the project model, not by the engine
dev_countries = []              # e.g. ["NL", "RU"] — where the team's test devices live
published_versions = []         # empty = every version counts as public
```

Secrets are never stored in the database or the toml. Token lookup order for a source:
1. environment variable (`APPMETRICA_TOKEN`);
2. `analytics/.env`;
3. user-level file `~/.config/game-analytics-kit/.env` (one token for every project of the same account).

## 3. Source interface (`gak/sources/base.py`)

A source knows how to list its tables, the fields of each table, and how to fetch one date
range of one table into a CSV file on disk. Everything else (planning, replace-by-range,
logging, flattening) is generic and lives in `sync.py` / `store.py`.

```python
@dataclass(frozen=True)
class Table:
    name: str                 # table name in SQLite, e.g. "events"
    fields: list[str]         # requested fields, in order, PII excluded
    date_field: str           # field whose date() fills the `date` column (event day)
    json_field: str | None    # field flattened into event_params, e.g. "event_json"
    default: bool             # part of the default sync set
    pii_fields: list[str]     # only requested with --with-device-ids
    types: Mapping[str, str]  # SQLite type per field, TEXT if absent
    device_field: str | None  # identifies the device; sampling keeps or drops whole devices by it

class Source(ABC):            # constructed as cls(options, token, token_origin, log); no network in __init__
    name: str                 # "appmetrica"
    token_env: str            # "APPMETRICA_TOKEN"
    def tables(self) -> list[Table]
    def check(self) -> str                      # "who am I connected to", no secrets
    def applications(self) -> list[dict]        # `ga.py apps`
    def connect(self) -> dict[str, str]         # resolve app; facts stored in meta as "<source>.<key>"
    def first_day(self) -> date | None          # default `since` (e.g. app creation)
    def fetch(self, table, fields, start, end, dest: Path, log, *, fresh=False) -> Path
                                                # CSV with header; fresh = remote must rebuild, no cache
    def warm(self, table, fields, start, end) -> None          # optional prefetch hint, background thread
    def rejected_fields(self, error_text, fields) -> list[str] # field drift: which fields a 400 names
# errors: SourceError (user must fix: token, access, quota), RequestRejected(text) for a refused request
```

Adding a second event source (Firebase BigQuery export, GameAnalytics, devtodev, Amplitude)
means one new module that implements this interface plus its fields module. The skills say
so explicitly; the first real source is AppMetrica.

## 4. CLI (`py analytics/ga.py <command>`)

| Command | What it does |
| --- | --- |
| `status` | kit version, config summary, token found or not (never print it), db size, tables with row counts and date ranges, last sync per source, days still in the fresh window |
| `apps [--source appmetrica]` | list applications the token can see (id, name, api_key, created, timezone) |
| `sync [--source appmetrica] [--tables events,installations\|all] [--since D] [--until D] [--chunk-days N] [--fresh-days N] [--refresh-after H] [--force] [--dry-run] [--no-prefetch] [--with-device-ids] [--recheck-fields] [--sample R] [--no-flatten] [--db PATH] [--background] [--wait [--timeout SEC]]` | pull data; idempotent; prints a live plan and progress, and per chunk the CSV size, rows kept/read, download and load time, rows/s and the real database growth; `--recheck-fields` asks again for fields the API once rejected; `--sample R` keeps a share of devices (overrides `sample`, refused if the database holds another rate); `--no-flatten` skips `event_params` (overrides `flatten_params = true`); a chunk that would crowd the disk is refused before parsing (section 5); `--background` runs it as a detached job (log `data/sync.log`, state `data/sync.state.json`) that outlives the agent's shell; `--wait` follows the job and returns its exit code, or 3 after `--timeout` (default 90 s, safely below every agent's per-command limit) if it still runs — the agent calls it again in a loop |
| `catalog [--since D] [--min-count N] [--limit N] [--max-events N] [--format md\|table\|json]` | event names × parameter keys: occurrences, devices, distinct values, sample values, numeric share; without `event_params` it flattens the latest `--max-events` (200k) events with `json_each` and says it sampled |
| `model scaffold [--out model/010_v_events.sql] [--min-share F] [--top N] [--since D] [--max-events N] [--force]` | writes a `v_events` view with one typed column per frequent parameter key (json_extract + CAST by observed type); the agent then edits it; reads parameters like `catalog` |
| `model apply` | executes `model/*.sql` in file-name order inside one transaction; reports errors with file and line |
| `query <name\|path.sql> [--param k=v ...] [--format table\|md\|csv\|json] [--limit N]` | runs a query from `queries/` (project) or `kit/gak/queries/` (generic); `list` shows both with their header comments |
| `sql "<statement>" [--param k=v ...] [--format ...] [--db PATH]` | ad-hoc read-only SQL (opens the db read-only); `--db` reads another database, e.g. a scratch sync |
| `import-csv <file> [--kind google_ads\|admob\|ga4\|play_console\|generic] [--table NAME] [--replace]` | loads a console export into `ext_<table>`; logs it in `imports` |
| `keymetrics [--since D] [--until D] [--by version\|country\|none] [--top N] [--min-devices N] [--players VIEW\|SELECT] [--life-days N] [--cap SEC] [--format table\|md\|csv\|json\|html] [--out FILE]` | the key-metrics table of block 1 (section 6): one column per cohort group (first version by default) plus all players; rows: players, D1/D3/D7, active time per player, sessions per player, session length, interstitial / rewarded impressions per player, ad ARPU, ad revenue, IAP (USD) when present. Sample-aware: absolute rows get an estimate row (sample ÷ rate) |
| `dropoff [--since D] [--until D] [--players VIEW\|SELECT] [--steps VIEW\|SELECT] [--version V] [--country CC] [--step-sec 30] [--max-sec 600] [--scope all\|first-day\|first-session] [--cap SEC] [--format ...] [--out FILE] [--svg FILE]` | the drop-off table of block 2: reached / lost / % lost of the previous row, first by the ordered steps the project defines (loading, FTUE: rows `device_id, step_no, step_name`), then by active-time buckets; a `sec` column in the steps adds the step time (median · p90 · max); `--svg` writes the chart |
| `ordinals (--events A,B \| --actions VIEW\|SELECT) [--max-n 15] [population, format flags]` | core actions by their number within a session: devices doing an action the 1st … Nth time in one session, % of the cohort, median and mean seconds into the session (`--actions` rows `device_id, session_id, ts, label [, sec]` for parameter-level actions or the project's own session unit) |
| `leaving (--events A,B \| --triggers VIEW\|SELECT) [--pause EVENTS\|VIEW\|SELECT] [--resume ...] [--ignore EVENTS] [--window 20] [population, format flags]` | what devices do right after an event: backgrounded within the window (pause events or `device_id, ts` rows), came back after it, did nothing else within it, never came back; a neutral event among the triggers is the baseline |
| `report new <slug> --title "..." [--kind full\|question] [--from vN]` | creates the next version folder from the kind's scaffold, prints its path |
| `report build <slug> [--version N] [--force]` | assembles report.html + artifact.html, updates meta.json and reports/index.html; a built version is final, `--force` only for fixing a broken build |
| `report index` | rebuilds reports/index.html |
| `selftest` | runs `kit/selftest.py` |

Exit code 0 on success, non-zero on any failure with the reason on stderr (one line; `report build` lists every unresolved placeholder).
All output is plain text that an agent can read; long listings are capped with a note.

## 5. Database

### Core tables (`schema_core.sql`, created by `store.ensure_schema`)

- one table per source table: `events`, `sessions_starts`, `installations`, `crashes`, `errors`,
  `revenue_events`, `ad_revenue_events`. Columns = source fields + `id INTEGER PRIMARY KEY`,
  `date TEXT` (event day), `load_date TEXT`. Ids that are uint64 are TEXT.
- `events.event_json_raw` keeps a payload that is not valid JSON, so `event_json` is always valid for `json_extract`.
- `event_params(event_id, date, load_date, event_name, key, value_text, value_num)` —
  flattened `event_json`; indexed on (key, value_text), (date, key), (event_id). About 140 bytes
  per parameter, so most of the database at 20-30 parameters per event; empty when synced with
  `flatten_params = false`. Generic queries never read it.
- `sync_log(source, table_name, day, loaded_at, rows, is_final)` — one row per day per table.
- `source_fields(source, table_name, accepted, rejected, updated_at)`.
- `meta(key, value)` — keys prefixed by source: `appmetrica.app_id`, `appmetrica.app_name`,
  `appmetrica.timezone`, `appmetrica.last_sync_at`, `appmetrica.sample_rate` (share of devices in
  this database), `appmetrica.flatten_params` (`1`/`0`, setting of the last sync).
- `imports(id, file, kind, table_name, rows, imported_at, sha256, preamble)` and `ext_*` tables (`preamble` keeps the title / date-range lines consoles put above the header).

Generic views (only core columns, no game parameters):
`v_event_catalog`, `v_dau`, `v_device_first_seen` (device, first event ts/day, first version,
first country), `v_installs` (latest installation per device with publisher/tracker, source
class paid/organic/unknown).

### Sync rules (lessons that cost real time — keep them)

- Pull in date **ranges** (7 days default), not per day: AppMetrica prepares queued exports
  one by one, a one-day request waits as long as a week.
- A chunk **replaces** all of its days in one transaction (DELETE by date range + INSERT).
  Rows have no id; hashing would merge genuine duplicates.
- Days older than `fresh_days` are final and never requested again (only `--force`).
  A fresh day is re-requested only when its last load is older than `refresh_after_hours`.
- Non-final ranges request `Cache-Control: no-cache`.
- Stream the CSV to a temp file first, then parse; never parse from the socket.
- SQLite connection in autocommit (`isolation_level=None`), explicit `BEGIN IMMEDIATE`.
- 202 = preparing (poll 5→60 s, print progress %), 429 = wait Retry-After, 400 "Try to use
  more parts" = raise parts_count, 401 = token problem (clear message).
- Unknown fields are removed from the request and remembered in `source_fields.rejected`.
- PII fields (advertising ids, IP, operator) are not requested unless `--with-device-ids`.
- The current day is always incomplete; say so in `status`.
- **Big games outgrow the disk.** A 7-day `events` export of a game with ~350 installs/day was
  1.4 GB of CSV (3-4 M rows); after 600k rows the database was 5.6 GB plus a 5.7 GB WAL. Levers:
  - `sample = r` / `--sample r`: keep a row iff `crc32(device_id) % 10000 < round(r * 10000)`
    (rows without a device id are kept). The same rule for every table keeps per-device joins
    whole. Applied while reading the CSV, before insertion. The rate is fixed per database
    (`meta.<source>.sample_rate`; a database synced before sampling holds all devices): another
    rate is refused — use a new `--db` or delete the database. `status` prints
    "sample: 10% of devices — multiply absolute counts by 10"; reports record `db_snapshot.sample_rate`.
  - `flatten_params = false` / `--no-flatten`: `event_params` is not written (the range's old
    rows are still deleted). `catalog` and `model scaffold` then flatten the latest 200k events
    (or a `--since` window) with `json_each` into a temp table of the same shape and say so.
- **Disk guard.** After a chunk's CSV is downloaded and before parsing, projected growth =
  CSV bytes × sample × factor; the chunk is refused when the peak (growth × 2: the WAL holds a
  copy until the checkpoint) exceeds 60 % of the free space on the database's drive, with the
  CSV size, growth, peak, free space and the levers (`--sample 0.1`, `--no-flatten`, shorter
  `--since`) in the error. A CSV over 500 MB prints the projection as a warning even when it fits.
  Factors, measured with the selftest generator (database bytes per CSV byte): stored as is
  1.1-1.6 → `PLAIN_FACTOR = 1.6`; `events` with `event_params` 3.2 at ~3 params/event and 5.4 at
  25 params/event (~140 bytes per parameter) → `FLATTEN_FACTOR = 6.0`; WAL peak = 1.0 × growth.
  After a table's first chunk the growth it really showed is used when larger.
- `PRAGMA wal_checkpoint(TRUNCATE)` after every chunk commit and at the end of a sync, so the
  WAL never keeps a second copy of the data.

### Generic queries (`kit/gak/queries/`)

`overview`, `sync_health`, `event_volume`, `dau`, `retention` (D1/D3/D7 by first-seen day),
`installs_by_source` (per day: paid / organic / unknown, by country), `app_versions`,
`ad_revenue_daily` (from ad_revenue_events: date, country, type, network, revenue, impressions),
`crashes_errors`. First line of each file: `-- <title>`; parameters as `:since`, `:until`.

### Standard tables (`metrics.py`: `keymetrics`, `dropoff`)

Every full review starts from the same four tables, so they are computed by the engine, not
re-derived per report: key metrics and drop-off (`metrics.py`), actions by ordinal and leaving
after events (`sequences.py`). Both read core tables only, plus two optional project inputs given as a
view / table name or a `SELECT`: the population (`--players`, rows with `device_id`; default
`v_players` when the model has it, else every device) and the ordered steps (`--steps`, rows
`device_id, step_no, step_name`). Definitions (they match the data-model skill's metrics):

- cohort = devices whose first event (`v_device_first_seen`) falls in `--since..--until`,
  grouped by first version or first country;
- DN = any event on first day + N, only over devices whose day N is complete (earlier than the
  last loaded day), with the n of those devices;
- active time = per session, the sum of gaps between consecutive events, each capped at
  `--cap` (600 s); sessions = distinct `session_id`; activity after the first day counts
  unless `--life-days N` limits it to life days 0..N-1;
- ads: `ad_revenue_events.ad_revenue_type` names or AppMetrica codes (4 = interstitial,
  3 = rewarded, 2 = banner); revenue in USD as sent; IAP = `revenue_events` in USD;
- drop-off by steps: a device reached step k when its highest step is k or later (a lost
  event does not break the funnel); by time: a device reached t seconds when its active time
  in `--scope` is at least t; lost = reached at the previous row − reached at this one;
- ordinals: the Nth occurrence of an action within one session; time = seconds since the
  session's first event (or the project's `sec`);
- leaving: per trigger, device-level shares — a pause within the window, a return within the
  window after that pause, no other event within the window, no event at all afterwards;
- key-metrics columns: the `--top` largest groups with at least `--min-devices` devices (10).

In a sampled database rates stay as they are and every absolute row gets an estimate
(÷ rate, marked "est."). `--format html` writes a ready `.tablebox` fragment in the report
language that the report embeds with `{{html:assets/<file>.html}}`.

## 6. Reports

Reports are the product. A report answers the owner's questions with numbers, charts and
screenshots, and survives being forwarded without Claude: `report.html` is one file that opens
from disk (fonts from Google Fonts, everything else inline, images as data URIs).

### Kinds, blocks and the title

Every report has the same skeleton, so a reader and an agent find things in the same place.
Two kinds (`report new --kind`, recorded as `meta.json.kind`):

- `full` — the full review of a game over a period; every block below.
- `question` — one question (a build, a funnel, UA payback); blocks 1, 6, 7 always, of 2–5
  only those the question needs, in the same order.

| # | Block id | Content |
| --- | --- | --- |
| 1 | `summary` | key-metrics table (rows: D1/D3/D7, active time, sessions, session length, interstitials and rewarded per player, ARPU, revenue, players; columns: build versions — `keymetrics`) or, in a question report, 3–4 tiles; then short answers to the questions asked |
| 2 | `product` | everything about the game except money: retention, funnels, core loop, economy; the drop-off table by steps and by 30 s of active time (`dropoff`) is mandatory in a full review |
| 3 | `revenue` | ads by format, placement, network (eCPM, impressions per player) and purchases |
| 4 | `tech` | technical problems and analytics defects: duplicates, empty or broken fields, source mismatches |
| 5 | `countries` | the country split in one place |
| 6 | `hypotheses` | `H1`, `H2`… each: claim → the numbers it rests on (links to blocks 2–5) → how to test it (metric and threshold) → confidence |
| 7 | `actions` | recommendations, each linked to a hypothesis, with the expected effect and how to measure it |
| — | `data`, `method` | data requests (optional), method (required) |

Block numbers are fixed in both kinds (hypotheses are always 6), so a question report may
read 1, 2, 6, 7. Facts and interpretation are marked apart (`.interp`); every number used in
blocks 1, 6 and 7 appears in a table or chart of blocks 1–5.

The title (`h1`, `meta.title`) is the request: what was asked, about which game, version and
period — «MyGame 0.2.0, 08–21.09: полный разбор», «Где теряем новичков в первой сессии».
The thesis goes into the standfirst and `meta.subtitle`. The slug comes from the request too
(`full-review-2026-09-08-21`, `first-session-loss`): a new period is a new slug, a correction
of the same review is a new version.

### Versioning

- `report new <slug>` creates `reports/<slug>/vNNN/` (NNN = next number, zero-padded to 3),
  `--from vK` copies `report.src.html`, `report.md` and `assets/` from version K and keeps its
  kind (a version made before kinds existed stays without one and without the structure check).
- A built version is immutable. Any change after build → a new version. `meta.json` records
  `slug, version, kind, title, subtitle, created_at, built_at, question, data_window {since, until},
  db_snapshot {tables: {name: {rows, min_date, max_date}}}, kit_version, project_git_commit,
  previous_version, sources_used, language`.
- `reports/index.html` lists every report (latest version first, with title, date, one-line
  summary taken from `meta.json.subtitle`) and the history of versions with links.
- When a new version supersedes an old one, the body starts with a short "What changed since
  vK" block (the report skill enforces it).

### Build

`report.src.html` is a body fragment. Placeholders the builder resolves:
- `{{svg:assets/name.svg}}` → the SVG inline;
- `{{img:assets/name.png}}` → `data:image/png;base64,...` (png, jpg, webp, gif);
- `{{html:assets/name.html}}` → the fragment inline (tables written by `keymetrics` / `dropoff --format html`);
- `{{meta:field}}` → value from meta.json (title, version, data_window.since ...) and the computed
  version_label, built_date and window (`08–21.09.2026` / `Sep 8–21, 2026`);
  an empty field is an error, so a report cannot be built without its data window.
- HTML comments in `report.src.html` are dropped before resolving, so the scaffold can carry commented examples.
The builder wraps the body with `theme.css` into `shell.html` → `report.html`, and writes the
same content without the document shell → `artifact.html` (first line `<title>`). It fails
if any placeholder is unresolved or any referenced asset is missing.

Structure check (kinds `full` and `question`; nothing is written when it fails, every problem
is listed): the required blocks exist as `<section id="...">` in the order of the table above;
ids are unique and every `href="#..."` points to an existing id; every hypothesis
(`.hyp`, id `h1`, `h2`…) has a confidence mark and at least one link into the evidence blocks;
every recommendation (`.act` in `#actions`) links to a hypothesis and has an expected effect
(`.eff`) and a measure (`.measure`).

### Theme and components (`theme.css`)

Light and dark palettes as CSS custom properties on `:root`, redefined under
`@media (prefers-color-scheme: dark)` guarded by `:root:not([data-theme="light"])` and again
under `:root[data-theme="dark"]`; `body` has an explicit background. Fonts: Oxanium (display),
IBM Plex Sans (body), IBM Plex Mono (data) from Google Fonts with system fallbacks.
Semantic colors: `--flow` (normal path / organic), `--ad` (ads / paid), `--loss` (lost
players, bad), `--good` (revenue, good), plus chart series tokens `--c-1..--c-6` and neutral
`--c-old`/`--c-unk`.

Components (class names are the API the report skill documents):
`.wrap`, `.masthead`, `.eyebrow`, `h1`, `.standfirst`, `.tiles > .tile(.warn|.ad|.good) > .k/.v/.n`,
`.answers > .ans > .q + div`, `h2 + .lede`, `.note`, `.calc`, `figure > .figbox (> .legend) + figcaption`,
`.shot > .tag + .frame > img`, `.shots2` (two screenshots side by side),
`.tablebox > table` with `td.n` numeric, `td.bad`, `td.ok`, `tr.total`, `.tnote`,
`.cards > .card(.hot|.adc|.okc) > .cnt/h4/p`, `.acts > .act > div > h4/p/.eff/.measure/.why` (numbered
recommendations), `.method`, and for the fixed skeleton: `nav.toc` (links to the blocks),
`section.block#<id> > h2 > .bn` (block number), `.hyps > .hyp#hN > .hid/.conf(.high|.mid|.low)/h4/.basis/.test`
(hypotheses), `.interp` (interpretation, set apart from facts), `table.kpi` (key metrics, versions as
columns), `td.est` / `.est` (an estimate scaled from a device sample). Everything responsive down to
400 px; tables and figures scroll inside their box.

### Charts (`charts.py`)

Pure functions returning an SVG string that uses CSS classes (`.grid .ax .val .lab .ann .band
.refl` and series classes `.s1..s6`, `.s-old`, `.s-unk`, `.s-good`, `.s-bad`), so both themes work:
`bar(categories, values, ...)`, `grouped_bars(categories, series, ...)`,
`stacked_bars(categories, series, ...)`, `hbars(labels, values, ...)`,
`line(x, series, ...)`, `ranked_bars(values, highlight_top=N, mean_line=True, ...)`,
`legend_html(series)`. Every mark carries `<title>` for hover. Decimal separator and
thousands separator follow the report language (ru: `0,13`, `1 234`). Numbers are never
formatted with str.replace on the whole SVG string (that corrupts coordinates).

## 7. Skills

All skills are English, follow the Agent Skills format (a folder with `SKILL.md` whose YAML
front matter has only `name` and `description`), keep `SKILL.md` short and push details into
`references/*.md`. They must work in both Claude Code and Codex: no Claude-only front matter,
no `${CLAUDE_SKILL_DIR}`; every command is run from the project root as
`py analytics/ga.py ...`. Reports are written in `analytics.toml` → `project.report_language`.

| Skill | Job |
| --- | --- |
| `analytics-kit` | Entry point. What the kit is, file layout, command cheat sheet, which skill to use next, how to update the kit. Triggers on general "analytics" requests. |
| `analytics-connect-appmetrica` | Connect AppMetrica: find the SDK key in code, get the OAuth token (user steps), resolve the app, first sync, verify. Includes the Logs API contract and pitfalls. |
| `analytics-data-model` | Build the project model on top of core tables: catalog → v_events → device/cohort tables → dev-device filters → attribution → project queries; record facts in notes/project.md. |
| `analytics-project-audit` | Read the game code and the data: which SDKs, which events and parameters, where they fire, what is missing or broken, which external data is needed; produce an audit report and a data-request checklist. |
| `analytics-import-external` | Get data from Google Ads, AdMob, GA4, Play Console / App Store Connect: exactly what to export, CSV import, reading screenshots, reconciling with event data (conversion ≠ install). |
| `analytics-research` | The researcher: question → refresh data → hypotheses → queries → verification pass → versioned report → findings log. Includes the default set of a full review (key metrics by version, drop-off by steps and 30 s, loading step times, core actions by ordinal, leaving after negative events, ads, economy, technical checks, countries). |
| `analytics-report` | How to write and build a report: the seven blocks and the title rule, style, charts, screenshots, hypotheses and linked recommendations, versioning, publishing (Claude Artifact when available; the local HTML always). |

## 8. Non-goals for v0.1

API connectors for Google Ads / AdMob / GA4 / Play Console (CSV and screenshots instead),
iOS-specific sources, dashboards, scheduled runs.
