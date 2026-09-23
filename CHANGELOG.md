# Changelog

## 0.3.0 — 2026-09-22

One structure for every report, and the standard tables of a full review computed by the
engine. Owner feedback: the conclusions were right, but every report was organised
differently.

- Reports have a fixed skeleton: 1 summary (key metrics by build version + short answers),
  2 product, 3 revenue, 4 technical, 5 countries, 6 hypotheses, 7 recommendations, then data
  requests and method. `report new --kind full|question` writes the scaffold of the kind with
  block names in the report language; `report build` checks the skeleton (blocks and order,
  unique ids, links, every hypothesis with a confidence mark and an evidence link, every
  recommendation linked to a hypothesis with its effect and measure) and lists every problem.
- The title of a report is the request (game, version, period, what was asked); the thesis
  moved to the standfirst (`meta.subtitle`).
- `ga.py keymetrics`: the key-metrics table — players, D1/D3/D7, active time, sessions,
  session length, interstitials / rewarded per player, ARPU, revenue, IAP — one column per
  first version (or country), sample-aware (estimate rows).
- `ga.py dropoff`: the drop-off table — ordered loading/FTUE steps from a project view, then
  every 30 s of active time; `--svg` draws the chart.
- `ga.py ordinals`: core actions by their number within a session (devices, % of the cohort,
  median and mean time into the session); `ga.py leaving`: who backgrounds, stops or never
  returns right after an event, next to a neutral event (pause/resume as events or as rows of
  a flag event). A `sec` column in the steps view adds the step time to the drop-off table
  (loading times). `keymetrics --min-devices` keeps tiny builds out of the columns.
- All four write a ready fragment with `--format html --out`, embedded by the new placeholder
  `{{html:assets/<file>.html}}`; `{{meta:window}}` prints the data window as people write it.
- Theme: table of contents, numbered blocks, hypotheses with confidence, recommendations
  with effect and measure, interpretation set apart from facts, key-metrics and drop-off
  tables that fit a phone, estimates marked ≈.
- Skills: analytics-report (skeleton, title rule, components), analytics-research (full
  review playbook: key metrics, drop-off, loading times, core actions by ordinal, leaving
  after negative events, economy, ads, technical checks, countries), analytics-data-model
  (SQL patterns §11–19: new players, steps view, loading times, ordinals, negative events,
  economy, placements, technical checks, countries), project-audit report in the skeleton.
- The sample report is now a full review and a question report on made-up data.
- Tested end to end: a fresh Claude run made a full review of a real game in 15 minutes
  (docs/TEST_LOG.md, run 4); what it missed became the new commands above.
- Docs: README in English and Russian (quick start, Claude and Codex, reports, big games,
  updating, token security, troubleshooting), CONTRIBUTING, MIT license, issue templates;
  the test log and examples no longer name the test game.
- Public repository: a site on GitHub Pages (landing in English and Russian, the live example
  reports), CI on Linux, macOS and Windows with Python 3.11 and 3.13, SECURITY.md, badges.
- The example reports come in English and Russian (docs/examples/sample-report/en/, ru/); table
  notes of the standard tables print the data window as people write it.

## 0.2.3 — 2026-09-21

- Charts: a small non-zero value no longer prints as zero (`$0,004`, not `$0,00`); found in
  the research report of an end-to-end run, where revenue per player was a fraction of a cent.
- `sync --wait` shows a recap of the log tail on each call instead of the whole log.

## 0.2.2 — 2026-09-21

- The foreground wait rule moved into the kit's conventions and the data-model preconditions:
  the fourth run loaded analytics-data-model (not the connect skill) and again handed the wait
  to a scheduled wake-up.
- `ga.py` prints a note when run from inside `analytics/` instead of the project root.

## 0.2.1 — 2026-09-21

- `sync --wait` returns after 90 s by default (was 540 s): Claude Code gives a command 2 minutes
  unless told otherwise, moved the long wait to its own background, scheduled a wake-up and
  ended the headless run — the third end-to-end run. Skills now forbid handing the waiting to
  the environment and ask for a foreground loop on `sync --wait`.
- analytics-kit: do not `cd analytics` (the test agent did and broke its code searches).

## 0.2.0 — 2026-09-21

Big games. The second end-to-end run hit a game with ~500k events a day: one 7-day chunk was
a 1.4 GB CSV and the database grew ~6 KB per event (event_params), 30+ GB for a week.

- Device sampling: `sample = R` in `[sources.appmetrica]` or `sync --sample R` keeps a
  deterministic hash-selected share of devices, the same set in every table; the rate is fixed
  per database and shown by `status`.
- `flatten_params = false` / `sync --no-flatten`: no event_params; `catalog` and
  `model scaffold` read a bounded sample of event_json instead (`--max-events`).
- Disk guard: after download, before parsing, the projected peak (growth + WAL copy) is compared
  with free space; the chunk is refused with the sizes and the levers. Warning above 500 MB.
- WAL checkpoint after every chunk; per-chunk line with CSV size, rows/s and database growth.
- Skills: measure one day into a probe database before the first big pull; volume tiers;
  reading sampled numbers (divide absolute counts by the rate).

## 0.1.1 — 2026-09-21

- `sync --background` runs the sync as a detached process that outlives the agent's shell
  and session (log `data/sync.log`, state `data/sync.state.json`); `sync --wait` follows it
  and returns its exit code, or 3 after `--timeout` while it still runs; `status` shows the job;
  a second sync is refused while a job is alive. Found by the first end-to-end run: a headless
  agent started the sync in its own background and ended, killing it.
- Skills: never end a turn while your sync runs; the detached-job protocol everywhere a long
  sync is mentioned.
- `tests/transcript_summary.py` for reading headless agent runs; installer prints UTF-8 on
  legacy Windows consoles.

## 0.1.0 — 2026-09-21

First version, extracted from the analytics work on a Unity mobile game.

- Engine `gak`: AppMetrica Logs API sync by date ranges with day replacement, SQLite store,
  event catalog, `v_events` scaffold, project model apply, queries, CSV import from ad and store
  consoles, versioned HTML reports with light/dark theme and SVG charts.
- Seven skills for Claude Code and Codex: kit, connect-appmetrica, data-model, project-audit,
  import-external, research, report.
- `install.py`: install, update, link and uninstall into a project.
