# Command reference

Run from the project root. Windows: `py analytics/ga.py <command>`; macOS/Linux:
`python3 analytics/ga.py <command>`. Exit code 0 on success, non-zero with a one-line
reason on stderr. Long listings are capped with a note — narrow the query instead of
asking for more rows.

Dates are `YYYY-MM-DD` in the app's time zone (see `status` / `meta`).

## status

```
py analytics/ga.py status
```

Kit version, config summary, whether a token was found (never the token), database size,
every table with row count and date range, last sync per source, and which days are still
inside the fresh window (they can still change). Run it at the start of every task and
after every sync.

## apps

```
py analytics/ga.py apps [--source appmetrica]
```

Applications the token can see: numeric id, name, `api_key` (the SDK key), creation date,
time zone. Use it to match the SDK key from the code to the numeric id.

## sync

```
py analytics/ga.py sync [--source appmetrica] [--tables events,installations|all]
    [--since D] [--until D] [--chunk-days N] [--fresh-days N] [--refresh-after H]
    [--force] [--dry-run] [--no-prefetch] [--with-device-ids] [--db PATH]
```

| Flag | Meaning |
| --- | --- |
| `--tables` | comma list or `all`; default = `tables` in `analytics.toml` (`events,sessions_starts,installations`) |
| `--since`, `--until` | first and last day to pull (inclusive); default since = `since` in the toml, else the app creation date |
| `--chunk-days N` | days per export request (default 7) |
| `--fresh-days N` | days younger than this are not final and may be re-pulled (default 7) |
| `--refresh-after H` | re-pull a fresh day only if its last load is older than H hours (default 12) |
| `--force` | re-pull even final days |
| `--dry-run` | print the plan (chunks, days, skipped days) and stop |
| `--no-prefetch` | do not queue the next chunk while the current one downloads |
| `--with-device-ids` | also request advertising ids, IP, operator (PII) — only with the owner's consent |
| `--db PATH` | write into another database file (scratch db for an urgent table while another sync runs) |
| `--background` | start the sync as a detached process that outlives your shell and session; log in `data/sync.log`, state in `data/sync.state.json` |
| `--wait [--timeout SEC]` | follow the running job, streaming its log; returns when it ends (its exit code) or after `--timeout` (default 90 s) with exit code 3 = still running: call it again right away, in the foreground |

Idempotent: a chunk replaces all of its days. Safe to rerun after a failure.
Never run two syncs into the same database file at once ("database is locked"); the kit
refuses to start one while a background job is alive. Long pulls: `sync --background ...`,
then `sync --wait` until it reports done — never end a session with your job still running.

## catalog

```
py analytics/ga.py catalog [--since D] [--min-count N] [--format md|table|json]
```

Event names × parameter keys: occurrences, devices, distinct values, sample values, share
of numeric values. `--since` = the release day of a build to see only what that build
sends; `--min-count` hides rare keys; `--format json` for scripts.

## model

```
py analytics/ga.py model scaffold [--out model/010_v_events.sql] [--top N]
py analytics/ga.py model apply
```

`scaffold` writes a `v_events` view with one typed column per frequent parameter key
(`--top N` keys); `--out` is relative to `analytics/`. Never scaffold over an edited
`010_v_events.sql`: to see what a new build adds, scaffold into a path outside `model/`
(for example `--out data/v_events_scaffold.sql`, git-ignored and never applied) and copy
the new columns by hand.
`apply` runs every `analytics/model/*.sql` in file-name order inside one transaction and
reports errors with file and line. Run it after every sync if the model has tables.

## query

```
py analytics/ga.py query list
py analytics/ga.py query <name|path.sql> [--param k=v ...] [--format table|md|csv|json] [--limit N]
```

Runs a query from `analytics/queries/` (project) or `analytics/kit/gak/queries/`
(generic). `list` shows both with their header comments. Parameters in SQL are `:since`,
`:until`, etc.; pass them as `--param since=2026-08-01 --param until=2026-08-31`.
Generic queries: `overview`, `sync_health`, `event_volume`, `dau`, `retention`,
`installs_by_source`, `app_versions`, `ad_revenue_daily`, `crashes_errors`.

## sql

```
py analytics/ga.py sql "SELECT event_name, COUNT(*) FROM events GROUP BY 1 ORDER BY 2 DESC" [--format md]
```

Ad-hoc, read-only. Useful for `PRAGMA table_info(events)` and quick checks. Anything
longer than a few lines belongs in `analytics/queries/` or in a script in a report's
`work/` folder. To combine the main database with a scratch file made by `sync --db`,
use a Python script with `sqlite3` and `ATTACH DATABASE`.

## import-csv

```
py analytics/ga.py import-csv <file> [--kind google_ads|admob|ga4|play_console|generic] [--table NAME] [--replace]
```

Loads a console export into an `ext_<table>` table and logs it in `imports` (file, kind,
rows, sha256). `--table` names the table (without `ext_`; default: from the file name);
`--replace` reloads it. The file path is looked up from the current folder first, then
from `analytics/`. App Store Connect and other consoles use `--kind generic`.

## keymetrics

```
py analytics/ga.py keymetrics [--since D] [--until D] [--by version|country|none] [--top N]
    [--players VIEW|SELECT] [--life-days N] [--cap SEC] [--format table|md|csv|json|html] [--out FILE]
```

The key-metrics table of block 1 of every report. Cohort = devices whose first event is in
`--since..--until` (default: everything loaded) among `--players` (a view/table with
`device_id` or a `SELECT`; default `v_players` when the model has it). Columns: first
version (`--by version`, default), first country, or none, plus all players; a group with
fewer than `--min-devices` (10) devices gets no column of its own. Rows:
players, D1/D3/D7 with the n of devices whose day is over, active time per player (mean,
median), sessions per player, session length, interstitial / rewarded (banner, other when
present) impressions per player, ad ARPU, ad revenue, IAP payers and revenue (USD) when
`revenue_events` has rows. A sampled database adds estimate rows (sample ÷ rate, marked
`~`/`≈`). `--life-days 7` counts only life days 0–6 (compare builds of different age).
`--format html --out analytics/reports/<slug>/vNNN/assets/keymetrics.html` writes the table
for `{{html:assets/keymetrics.html}}` in the report language; `--out` is relative to
`analytics/` (a path starting with `analytics/` works too).

## dropoff

```
py analytics/ga.py dropoff [--since D] [--until D] [--players VIEW|SELECT] [--steps VIEW|SELECT]
    [--version V] [--country CC] [--step-sec 30] [--max-sec 600] [--scope all|first-day|first-session]
    [--cap SEC] [--format table|md|csv|json|html] [--out FILE] [--svg FILE]
```

The drop-off table of block 2: reached / lost / % lost of the previous row / % of the
cohort. First the ordered steps from `--steps` (rows `device_id, step_no, step_name`; a
device counts at a step when its furthest step is that one or later; an optional `sec`
column — the time the step took — adds median · p90 · max per step), then every
`--step-sec` of active time up to `--max-sec` (active time = gaps inside a session, each up
to `--cap`; `--scope` limits it to the first day or the first session). Filters by first
version / country. `--svg` writes the chart of the time part. The note line counts devices
that installed in the window but sent no event (lost before the cohort starts).

## ordinals

```
py analytics/ga.py ordinals (--events A,B | --actions VIEW|SELECT) [--max-n 15]
    [--since D] [--until D] [--players VIEW|SELECT] [--format table|md|csv|json|html] [--out FILE]
```

Core actions by their number within a session: for each action and N = 1 … `--max-n`, the
devices that did it an Nth time in one session, their share of the cohort, and the median /
mean seconds since the session's first event. `--actions` takes rows `device_id, session_id,
ts, label [, sec]` — a parameter-level action, or the project's own session unit (a launch
number) instead of the SDK `session_id`; `sec` replaces the wall clock with the game's own
play-time counter. The html output is one table per action.

## leaving

```
py analytics/ga.py leaving (--events A,B | --triggers VIEW|SELECT) [--pause EVENTS|VIEW|SELECT]
    [--resume EVENTS|VIEW|SELECT] [--ignore EVENTS] [--window 20]
    [--since D] [--until D] [--players VIEW|SELECT] [--format ...] [--out FILE]
```

What devices do right after an event, as shares of the devices that had it: backgrounded
within `--window` seconds (a pause event), back within the window after that pause, nothing
else within the window, never came back. `--pause` / `--resume` are event names, or rows
`device_id, ts` when the game sends one focus event with a flag (`has_focus = False`).
`--ignore` lists events that are not the player acting (heartbeats, the focus events
themselves). Put a neutral event among the triggers (a purchase, a level start): the negative
events mean something only next to it.

## report

```
py analytics/ga.py report new <slug> --kind full|question --title "<the request>" [--from vN]
py analytics/ga.py report build <slug> [--version N]
py analytics/ga.py report index
```

`new` creates `analytics/reports/<slug>/vNNN/` (next number) from the scaffold of the kind
(`full`: all seven blocks; `question`, the default: blocks 1, 6, 7 + those of 2–5 it needs),
block names in the report language, and prints its path; the title is the request (game,
version, period, what was asked). `--from vK` copies `report.src.html`, `report.md` and
`assets/` from version K and carries over `kind`, `subtitle`, `question`, `data_window`,
`sources_used` in `meta.json`. `{{meta:window}}` prints the data window as people write it
(`08–21.09.2026`).
`build` resolves `{{svg:...}}`, `{{img:...}}`, `{{html:...}}`, `{{meta:...}}`, writes
`report.html` and `artifact.html`, updates `meta.json` and `reports/index.html`; it fails
on any unresolved placeholder, missing asset or empty meta field it needs, and for the
kinds `full` / `question` on a broken skeleton (missing or misordered block, duplicate id,
a link to no id, a hypothesis without confidence or evidence link, a recommendation without
a hypothesis link, `.eff` or `.measure`), listing every problem; it warns about TODO markers
left from the scaffold. A built version is final: `build` refuses to build it again — changes
go into `report new <slug> --from vK`. `index` rebuilds `reports/index.html`.

## selftest

```
py analytics/ga.py selftest
```

Offline tests of the engine with synthetic data (no token, no network).
