---
name: analytics-kit
description: "Entry point of game-analytics-kit, the local analytics toolkit installed in this game project (analytics/ga.py, a SQLite database, versioned HTML reports). Explains what the kit is, the file layout, every command, the first-run sequence, how to update the kit, and which sibling skill to use next. Use for general analytics requests or when unsure where to start: 'analytics', 'game metrics', 'what can we measure', 'update the kit', «аналитика», «что у нас с метриками», «с чего начать аналитику», «обнови кит аналитики». Once the job is clear, switch to the specific skill: analytics-connect-appmetrica (connect, sync, token), analytics-data-model (events, views, dev devices), analytics-project-audit (what the code tracks), analytics-import-external (Google Ads, AdMob, GA4, Play exports), analytics-research (answering a product question), analytics-report (writing and publishing a report)."
---

# Game analytics kit

The kit pulls a game's raw analytics (AppMetrica Logs API first) into a local SQLite
database, lets you model it for this project, research product questions with SQL and
Python, and publish versioned, self-contained HTML reports. The engine is generic; every
game-specific thing (event meaning, filters, queries, notes, reports) lives in project
files that you write.

## Conventions for every analytics task

- Run every command from the project root: `py analytics/ga.py <command>`. Do not `cd analytics` — paths to the game code in your searches and scripts are relative to the root.
- If `status` shows a running sync job and your task needs its data, wait for it yourself:
  call `py analytics/ga.py sync --wait` in the foreground again and again (each call returns
  within ~90 s; exit 3 = still running) until it reports done. Never end your turn to "resume
  later" and never hand the waiting to background shells or scheduled wake-ups — a
  non-interactive run is not resumed, and the owner gets half a job.
  On macOS/Linux use `python3 analytics/ga.py <command>` instead of `py`.
  The engine is stdlib-only; nothing to install. A failing command exits non-zero with a
  one-line reason on stderr.
- Write reports and notes in the language set in `analytics/analytics.toml` →
  `[project].report_language` (default `ru`). Talk to the owner in the owner's language.
- Before any work read `analytics/notes/project.md` (durable facts about this project's
  data) and the top of `analytics/notes/findings.md` (dated conclusions, newest first),
  then run `py analytics/ga.py status`. Never re-derive a filter or re-argue an owner
  decision that is already recorded there.
- The unit of analysis is the device. Developer and test devices are excluded by the
  project model, not ad hoc in each query.
- Write the n next to every rate, say which clock (time zone) a day-level number uses,
  and treat today (and the last few days) as incomplete.

## File map

| Path | What it is | Who edits |
| --- | --- | --- |
| `analytics/ga.py` | launcher for every command | nobody |
| `analytics/analytics.toml` | project config: sources, sync window, `[filters]` | you, with the owner |
| `analytics/.env` | secrets (`APPMETRICA_TOKEN=`), git-ignored | the owner |
| `analytics/kit/` | the engine, managed by `install.py` | **nobody** — overwritten on update |
| `analytics/data/analytics.db` | SQLite database, git-ignored | the engine (`sync`, `model apply`, `import-csv`) |
| `analytics/model/*.sql` | project views/tables on top of core tables, applied in file-name order | you |
| `analytics/queries/*.sql` | project queries, one per question, first line `-- <title>` | you |
| `analytics/imports/` | CSV exports and screenshots from the owner (`imports/raw/` is git-ignored) | the owner, you |
| `analytics/notes/project.md` | durable facts: SDK key, event meaning, dev devices, attribution, time zone | you |
| `analytics/notes/findings.md` | dated research conclusions, newest first | you |
| `analytics/reports/<slug>/vNNN/` | one report version: `report.src.html`, `report.md`, `assets/`, `work/`, `meta.json`, built `report.html` + `artifact.html` | you (`work/` is git-ignored) |
| `analytics/reports/index.html` | generated list of all reports | the engine |
| `.claude/skills/analytics-*`, `.agents/skills/analytics-*` | these skills (copies for Claude Code and Codex) | nobody — overwritten on update |

Core tables (created by the engine): `events`, `sessions_starts`, `installations`,
`crashes`, `errors`, `revenue_events`, `ad_revenue_events`, `event_params` (flattened
`event_json`), `sync_log`, `source_fields`, `meta`, `imports`, `ext_*` (imported CSVs).
Generic views: `v_event_catalog`, `v_dau`, `v_device_first_seen`, `v_installs`.

## Command cheat sheet

| Command | Use it to |
| --- | --- |
| `status` | see kit version, config, whether a token is found, tables with row counts and date ranges, last sync, days still fresh |
| `apps` | list AppMetrica apps the token can see (id, name, api_key, created, time zone) |
| `sync [--tables events,installations\|all] [--since D] [--until D]` | pull data; idempotent; `--dry-run` shows the plan |
| `catalog [--since D] [--min-count N] [--format md]` | see which events and parameter keys really arrive |
| `model scaffold` / `model apply` | generate `analytics/model/010_v_events.sql` / apply `analytics/model/*.sql` |
| `query list` / `query <name> [--param since=D]` | list or run project and generic queries |
| `sql "<SELECT ...>"` | ad-hoc read-only SQL |
| `import-csv <file> --kind google_ads\|admob\|ga4\|play_console\|generic` | load a console export into `ext_<table>` |
| `keymetrics [--since D] [--until D] [--by version\|country] [--players VIEW] [--format html --out FILE]` | the key-metrics table of every report: players, D1/D3/D7, active time, sessions, ads per player, ARPU, revenue — one column per build version |
| `dropoff [--steps VIEW] [--since D] [--until D] [--format html --out FILE --svg FILE]` | the drop-off table: loading/FTUE steps (with step time when the view has `sec`), then every 30 s of active time |
| `ordinals --events A,B` / `--actions VIEW` | core actions by their number within a session, with the median time into the session |
| `leaving --events A,B [--pause EVENTS\|VIEW] [--ignore EVENTS]` | who backgrounds, stops or never returns right after an event (negative events vs a neutral one) |
| `report new <slug> --kind full\|question --title "<the request>"` / `report build <slug>` / `report index` | create, build (checks the fixed skeleton) and index versioned reports |
| `selftest` | offline engine test with synthetic data (after install or update) |

Every flag, with examples: [references/commands.md](references/commands.md). Read it the
first time you use a command you have not used in this session.

## Which skill next

| Situation or request | Skill |
| --- | --- |
| No database yet, no token, a sync fails (401, 429), data needs refreshing | `analytics-connect-appmetrica` |
| Data is loaded but `analytics/model/` has only the scaffold or nothing; new events or builds appeared; numbers disagree between queries | `analytics-data-model` |
| "What do we track?", "which events are missing or broken?", before changing tracking code, a new SDK | `analytics-project-audit` |
| Numbers live in Google Ads, AdMob, GA4/Firebase, Play Console, App Store Connect; the owner sent console screenshots; CPI, ROAS, tCPA/tROAS | `analytics-import-external` |
| A full review of the game over a period («полный анализ»), or a product question: retention, churn, a build comparison, UA payback, ad monetization, organic installs | `analytics-research` |
| Findings must become a document, a report needs a new version or publishing | `analytics-report` |

## First run in a new project

1. `py analytics/ga.py status` and `py analytics/ga.py selftest` — the kit is installed
   and works offline.
2. **Connect** (`analytics-connect-appmetrica`): find the SDK key in the code, have the
   owner create the token, `apps`, fill `analytics/analytics.toml`, start the first sync
   as a detached job (`sync --background`) and follow it with `sync --wait`.
3. **Model** (`analytics-data-model`): while the sync runs, read the game's analytics code;
   when `sync --wait` reports done (never stop while it still runs), `catalog` → `v_events` → devices with the dev flag → sessions →
   `model apply` → sanity checks → `analytics/notes/project.md`.
4. **Audit** (`analytics-project-audit`): compare code with data, score coverage, list
   traps and external data needed; publish the `tracking-audit` report.
5. **Research** (`analytics-research`): answer the owner's first real question, finish
   with a report (`analytics-report`) and a `findings.md` entry.

## Secrets

The engine looks for `APPMETRICA_TOKEN` in: the environment variable, then
`analytics/.env`, then `~/.config/game-analytics-kit/.env` (one token for every project of
the same account). Never print, echo, log, commit or paste the token, never put it in a
command line, the database, `analytics.toml`, notes or reports. `status` only says whether
it was found. If the owner pastes a token into the chat, do not repeat it; ask them to
save it in one of the files above.

## Updating the kit

Run from any folder, pointing at the kit repository and this project:

```
py <kit repo>/install.py <project root> --update
```

Install and update are the same command (`--update` only makes the intent explicit;
add `--dry-run` to see the plan first). It replaces `analytics/kit/`, the launcher and the
skill folders it installed (they carry a `.gak-managed` marker) in `.claude/skills/` and
`.agents/skills/`; project files (`analytics.toml`, `.env`, `data/`, `model/`,
`queries/`, `imports/`, `notes/`, `reports/`) are never touched, other templates are only
copied when absent. After an update run `status` (kit version) and `selftest`, then
`model apply` to be sure the project model still builds.

## Do not edit

- `analytics/kit/` — a bug or missing feature in the engine is fixed in the kit repository
  and installed with `--update`; a local patch is lost on the next update. Work around it
  in project files (`model/`, `queries/`, a script in a report's `work/`) and tell the owner.
- The installed skill folders — same reason.
- A built report version — the builder refuses to rebuild it; make a new version with
  `report new <slug> --from vK` instead.
- Core tables — the engine owns them; `sql` opens the database read-only on purpose.
