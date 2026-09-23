---
name: analytics-data-model
description: "Builds and maintains this project's data model on top of the kit's core tables: reads the event catalog and the game's analytics code to learn what each event means, edits the typed v_events view, adds a per-device table (first day, version, country, paid/organic source, developer-device flag) and session time, writes project queries, applies and sanity-checks the model, and records event meaning in analytics/notes/project.md. Use after the first sync, when new events or builds appear, when queries disagree, or on 'set up the model', 'what events do we have', 'exclude test devices', «разбери события», «какие события приходят», «убери тестовые устройства», «настрой модель данных». Not for connecting or syncing (analytics-connect-appmetrica), judging tracking coverage in code (analytics-project-audit), or answering a product question (analytics-research)."
---

# Build the project data model

Commands run from the project root (conventions: the `analytics-kit` skill). The model is
plain SQL in `analytics/model/*.sql`, applied in file-name order by
`py analytics/ga.py model apply` inside one transaction. Everything project-specific that
a query would otherwise repeat (event meaning, types, dev devices, attribution classes,
session time) belongs here, once.

SQL patterns (first-event cohort, dev flag, capped gaps, D1, funnels, per-device
metrics, medians): [references/modeling-guide.md](references/modeling-guide.md) — read
it before writing any model file. Metric definitions that held up in practice:
[references/metrics.md](references/metrics.md) — read it before defining a metric.

## Preconditions

- `py analytics/ga.py status` shows `events` and `installations` with data. If it shows a
  running sync job, loop on `py analytics/ga.py sync --wait` in the foreground until it
  reports done (exit 3 = still running, call again at once) — read the game's analytics code
  between calls, but do not end your turn or schedule a wake-up while it runs.
- You have read `analytics/notes/project.md`; keep what is recorded there unless the data
  now contradicts it (then say so in the notes, dated).
- Note from `status` whether the database is a device sample and whether event parameters
  were flattened. Without `event_params`, `catalog` and `model scaffold` read a bounded
  sample of `event_json` and say so; the views you write use `json_extract` on `event_json`
  either way. With a device sample, write the rate into `notes/project.md` next to every
  absolute number you record.

## Procedure

1. **Catalog.** `py analytics/ga.py catalog --min-count 5 --format md` — then again with
   `--since <release day of the newest public build>` to see what the current build sends.
   Note events with very few devices, keys whose values never change, numeric keys with a
   low numeric share (mixed types), and events that fire far more often than players act.

2. **Read the game's analytics code** before naming anything. Find the wrapper that sends
   events, the event-name and parameter-name constants, value mappings (enums → strings)
   and every call site. For each event write down: when exactly it fires, once per
   install / session / occurrence, each parameter's meaning and unit, the value
   dictionary, and the first build that sends it (`git log -S "<event_name>"`). The
   `analytics-project-audit` skill has search patterns per engine if you need them.

3. **Scaffold v_events.** `py analytics/ga.py model scaffold --top 40` writes
   `analytics/model/010_v_events.sql`. Edit it:
   - column names = the parameter names from the code; types: ids and enums TEXT,
     counts INTEGER, money and seconds REAL, booleans INTEGER 0/1;
   - add core columns every query needs (device, session, timestamp, day, version,
     country) under short names;
   - drop pure noise (debug and test-tool events) in a `WHERE`; keep heartbeats and ticks
     but comment what they are;
   - a header comment: what the view is, which build's parameters it reflects.
   Never scaffold over the edited file: for a new build, scaffold into
   `--out data/v_events_scaffold.sql` (git-ignored, never applied) and copy new columns.

4. **Devices** — `analytics/model/020_devices.sql`: one row per device built from the
   engine views `v_device_first_seen` (first event day, time, version, country) and
   `v_installs` (source class paid / organic / unknown, install-row count), plus "ever ran
   an unpublished version", and `is_dev` + `dev_reason`. Dev rule: country in
   `[filters].dev_countries`, OR any version outside `[filters].published_versions`, OR
   extreme reinstalls, OR an explicit device list from the notes. SQL cannot read the toml: keep a copy of the filter values in the
   file with a comment pointing to `[filters]`. If `[filters]` is empty, propose values
   from `query app_versions`, installs by country and reinstall counts, and confirm them
   with the owner. Add a `v_players` view = devices where `is_dev = 0`.

5. **Sessions** — `analytics/model/030_sessions.sql`: per device and `session_id`: start,
   end, events, `active_sec` = sum of gaps between consecutive events capped at 600 s,
   and `span_sec` (last − first) for comparison only.

6. **Per-device metrics** (when research needs them) — `analytics/model/040_device_metrics.sql`:
   active days, D1 flag, sessions, active time, core-loop counts, ad impressions and
   revenue per device. Research then aggregates this one table many ways.

   **Inputs of the standard tables** (every report's key metrics and drop-off, see the
   modeling guide §11–12): `v_first_steps` (`device_id, step_no, step_name`: loading and
   tutorial steps in order, names in the report language) for `ga.py dropoff --steps`, and,
   when "first seen in the window" is not "new" in this project, `v_new_players` for
   `--players`. Check both with `py analytics/ga.py dropoff --steps v_first_steps` and
   `py analytics/ga.py keymetrics` before the first report.

7. **Project queries** — `analytics/queries/<name>.sql`, one question per file, first
   line `-- <title>`, parameters `:since` / `:until`, reading the model (`v_players`,
   `v_events`, `sessions`) rather than raw tables. Do not copy the generic queries
   (`query list` shows them).

8. **Apply.** `py analytics/ga.py model apply`; fix errors by file and line. Tables in the
   model are snapshots: re-run `model apply` after every sync.

9. **Sanity checks** — do all of them, write the numbers down:
   - row counts: `v_events` vs `events` in `status` (difference = rows you filtered on
     purpose); `devices` = `v_device_first_seen`; install rows with no event at all;
   - dev share: devices flagged, by `dev_reason`. A few to a few dozen is typical; if the
     rule catches a large share, a dev country is probably also a real market — ask;
   - D1 from your model vs `py analytics/ga.py query retention` on the same days;
   - read 3–5 raw device timelines in order (one dev, one paid, one organic, one who left
     after the first session): `sql "SELECT event_datetime, event_name, event_json FROM
     events WHERE appmetrica_device_id = '<id>' ORDER BY event_timestamp, id LIMIT 200"`.
     The story must make sense; if it does not, the model or the tracking is wrong.

10. **Record facts** in `analytics/notes/project.md` (report language; one fact per bullet
    with the date it was established and how it was checked): event dictionary
    (event → when it fires, key parameters with units, first build), the dev rule with
    counts, attribution mapping, the app time zone, whether `profile_id` is set, how
    reinstalls look in this project, dead or constant fields, heartbeat events and their
    effect on time metrics. Date every change of a rule.

## Rules

- Every model file is idempotent: `DROP VIEW/TABLE IF EXISTS` then `CREATE`; it only uses
  objects from core tables or earlier files; it has a header comment.
- Never `CAST` device or session ids to INTEGER — they are uint64 stored as TEXT.
- Cohorts are defined by a device's first event (day, version, country), not by its
  install row.
- A rule used by two queries moves into the model. A number that needs a caveat gets the
  caveat in the notes, next to the definition.
- Do not edit `analytics/kit/` or core tables; the model only adds objects.
