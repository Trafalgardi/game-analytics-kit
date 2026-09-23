# Modeling guide — SQL patterns

SQLite dialect (window functions available). Placeholders in angle brackets: event names
like `<match_end>`, parameter columns like `<ad_format>`. Core column names follow the
AppMetrica fields; confirm them before writing a file:

```
py analytics/ga.py sql "PRAGMA table_info(events)"
py analytics/ga.py sql "SELECT * FROM v_installs LIMIT 3"
py analytics/ga.py sql "SELECT * FROM v_device_first_seen LIMIT 3"
```

Every model file: header comment, `DROP ... IF EXISTS` then `CREATE`, only objects from
core tables or earlier files. Materialize (TABLE + index) what is heavy and reused; keep
`v_events` a VIEW. Tables are snapshots — `model apply` after every sync.

Timestamps: `event_timestamp` is Unix seconds; many events share a second. Order by
`(ts, id)`; `id` is load order, which is usually but not guaranteed to be send order. If
the game sends a sequence counter (e.g. a navigation step), prefer it for ordering.

## 1. `010_v_events.sql` — typed events

```sql
-- v_events: game events with typed parameters. Parameters as of build <x.y.z>.
DROP VIEW IF EXISTS v_events;
CREATE VIEW v_events AS
SELECT
  e.id,
  e.date                               AS day,
  e.event_timestamp                    AS ts,
  e.appmetrica_device_id               AS device_id,   -- uint64 as TEXT, never CAST
  e.session_id,
  e.app_version_name                   AS version,
  e.country_iso_code                   AS country,
  e.event_name,
  json_extract(e.event_json, '$.<mode>')                        AS <mode>,
  CAST(json_extract(e.event_json, '$.<level_index>') AS INTEGER) AS <level_index>,
  CAST(json_extract(e.event_json, '$.<duration_sec>') AS REAL)   AS <duration_sec>
FROM events e
WHERE e.event_name NOT IN ('<debug_event>');   -- test-tool noise only; keep heartbeats
```

For grouping by one parameter over many rows, use `event_params` instead of the view:

```sql
SELECT p.value_text AS <param>, COUNT(*) AS events,
       COUNT(DISTINCT e.appmetrica_device_id) AS devices
FROM event_params p JOIN events e ON e.id = p.event_id
WHERE p.event_name = '<event>' AND p.key = '<param>'
  AND p.date BETWEEN :since AND :until
GROUP BY 1 ORDER BY devices DESC;
```

## 2. `020_devices.sql` — first-event cohort + dev flag

```sql
-- devices: one row per device, cohort = first event. Dev rule mirrors [filters] in analytics.toml.
DROP VIEW  IF EXISTS v_players;
DROP TABLE IF EXISTS devices;
DROP TABLE IF EXISTS dev_filter_countries;
DROP TABLE IF EXISTS dev_filter_published;
DROP TABLE IF EXISTS dev_filter_devices;

-- Copies of [filters] (SQL cannot read the toml). Keep them in sync; leave a table empty
-- when the filter is empty.
CREATE TABLE dev_filter_countries (country TEXT PRIMARY KEY);
INSERT INTO dev_filter_countries VALUES ('<CC>');
CREATE TABLE dev_filter_published (version TEXT PRIMARY KEY);
INSERT INTO dev_filter_published VALUES ('<1.0.6>'), ('<1.0.8>');
CREATE TABLE dev_filter_devices (device_id TEXT PRIMARY KEY, note TEXT);  -- known team phones

CREATE TABLE devices AS
WITH unpublished AS (
  SELECT DISTINCT appmetrica_device_id AS device_id
  FROM events
  WHERE (SELECT COUNT(*) FROM dev_filter_published) > 0
    AND app_version_name NOT IN (SELECT version FROM dev_filter_published)
),
flagged AS (
  SELECT f.device_id,
         f.first_date,
         f.first_event_timestamp               AS first_ts,
         f.first_version,
         f.first_country,
         COALESCE(i.source_class, 'unknown')   AS source_class,   -- paid / organic / unknown
         COALESCE(i.install_rows, 0)           AS install_rows,
         CASE
           WHEN f.device_id IN (SELECT device_id FROM dev_filter_devices)      THEN 'listed'
           WHEN f.first_country IN (SELECT country FROM dev_filter_countries)  THEN 'dev_country'
           WHEN u.device_id IS NOT NULL                                        THEN 'unpublished_version'
           WHEN COALESCE(i.install_rows, 0) >= 3                               THEN 'reinstalls'  -- threshold from the distribution
         END AS dev_reason
  FROM v_device_first_seen f                 -- engine view: first event day, version, country
  LEFT JOIN v_installs  i ON i.device_id = f.device_id   -- latest install row + install_rows
  LEFT JOIN unpublished u ON u.device_id = f.device_id
)
SELECT *, (dev_reason IS NOT NULL) AS is_dev FROM flagged;

CREATE UNIQUE INDEX devices_id  ON devices(device_id);
CREATE INDEX        devices_day ON devices(first_date);
CREATE VIEW v_players AS SELECT * FROM devices WHERE is_dev = 0;
```

`v_installs.source_class` is the engine's generic rule (paid = a publisher that is not a
store; organic = Google Play / Google Search / App Store tracker; everything else
unknown). If this project knows better (another network name, a tracker that means paid),
override it here with a `CASE` on `i.publisher_name` / `i.tracker_name` and record the
rule in `analytics/notes/project.md`.

Checks after apply:

```sql
SELECT dev_reason, COUNT(*) FROM devices GROUP BY 1;             -- who is excluded and why
SELECT install_rows, COUNT(*) FROM devices GROUP BY 1 ORDER BY 1; -- reinstall distribution
```

Reinstalls: depending on platform and SDK a reinstall keeps the device id (repeated
installation rows, `is_reinstallation`) or produces a new one (the same model + country
appearing as a new device on a nearby day). Find out which happens here and record it.
Devices with an installation row but no custom event are absent from `devices`: count
them separately — they opened the app and the game sent nothing (often a crash or a hang
while loading).

## 3. `030_sessions.sql` — time in game with capped gaps

```sql
-- sessions: active time = sum of gaps between consecutive events, each capped at 600 s.
DROP TABLE IF EXISTS sessions;
CREATE TABLE sessions AS
WITH ordered AS (
  SELECT appmetrica_device_id AS device_id, session_id,
         event_timestamp AS ts,
         event_timestamp - LAG(event_timestamp) OVER (
           PARTITION BY appmetrica_device_id, session_id
           ORDER BY event_timestamp, id) AS gap
  FROM events
)
SELECT device_id, session_id,
       MIN(ts) AS start_ts, MAX(ts) AS end_ts, COUNT(*) AS events,
       SUM(MIN(COALESCE(gap, 0), 600)) AS active_sec,  -- a backgrounded app is not play
       MAX(ts) - MIN(ts)               AS span_sec     -- comparison only; inflated by background
FROM ordered
GROUP BY device_id, session_id;
CREATE INDEX sessions_device ON sessions(device_id);
```

If one build adds a periodic event (a heartbeat every 30 s in a match), gaps inside
matches shrink to 30 s but long quiet stretches that used to be capped now count fully:
that build's active time goes up without players playing longer. Compare builds on
events that exist in both, or state the bias direction.

## 4. `035_device_days.sql` — active days (D1/DN in one join)

```sql
DROP TABLE IF EXISTS device_days;
CREATE TABLE device_days AS
SELECT DISTINCT appmetrica_device_id AS device_id, date AS day FROM events;
CREATE UNIQUE INDEX device_days_idx ON device_days(device_id, day);
```

D1 by cohort day — only cohorts whose D1 day is over (the last day in the data is
incomplete; the last ~7 days can still grow through late delivery):

```sql
-- D1 by first day, players only
SELECT p.first_date,
       COUNT(*)                                        AS devices,
       SUM(dd.device_id IS NOT NULL)                   AS d1_devices,
       ROUND(100.0 * SUM(dd.device_id IS NOT NULL) / COUNT(*), 1) AS d1_pct
FROM v_players p
LEFT JOIN device_days dd
       ON dd.device_id = p.device_id AND dd.day = date(p.first_date, '+1 day')
WHERE p.first_date BETWEEN :since AND :until
  AND date(p.first_date, '+1 day') < (SELECT MAX(day) FROM device_days)
GROUP BY p.first_date ORDER BY p.first_date;
```

DN: replace `+1 day` with `+N day` in both places.

## 5. Funnel by device (ordered steps)

```sql
-- First-session funnel, players whose first day is in the window
WITH t AS (
  SELECT v.device_id,
    MIN(CASE WHEN v.event_name = '<loaded>'      THEN v.ts END) AS t_loaded,
    MIN(CASE WHEN v.event_name = '<menu_open>'   THEN v.ts END) AS t_menu,
    MIN(CASE WHEN v.event_name = '<match_start>' THEN v.ts END) AS t_start,
    MIN(CASE WHEN v.event_name = '<match_end>'   THEN v.ts END) AS t_end,
    SUM(v.event_name = '<match_start>')                         AS n_start,
    SUM(v.event_name = '<match_end>')                           AS n_end
  FROM v_events v JOIN v_players p ON p.device_id = v.device_id
  WHERE p.first_date BETWEEN :since AND :until
  GROUP BY v.device_id
),
s AS (
  SELECT *,
    t_loaded IS NOT NULL                        AS s_loaded,
    t_loaded IS NOT NULL AND t_menu  >= t_loaded AS s_menu,
    t_menu   IS NOT NULL AND t_start >= t_menu   AS s_start,
    t_start  IS NOT NULL AND t_end   >= t_start  AS s_end
  FROM t
)
SELECT COUNT(*)                         AS devices,
       SUM(s_loaded)                    AS loaded,
       SUM(s_loaded AND s_menu)         AS menu,
       SUM(s_loaded AND s_menu AND s_start)           AS started_1st,
       SUM(s_loaded AND s_menu AND s_start AND s_end) AS finished_1st,
       SUM(s_end AND n_start >= 2)      AS started_2nd_after_finishing,
       SUM(n_end >= 2)                  AS finished_2nd,
       SUM(n_end >= 3)                  AS finished_3rd,
       SUM(n_end >= 5)                  AS finished_5th
FROM s;
```

Keep "finished the first" and "started a second" as separate steps: a build can move the
loss from one to the other without changing the total. Add D1 as the last step with the
`device_days` join. Report each step as count, % of the first step and % of the previous.

## 6. Sequences in Python (next action, time on a screen)

Correlated subqueries per device get slow; one ordered pass is simpler. Run from the
project root in a report's `work/` script:

```python
import itertools, sqlite3
db = sqlite3.connect('file:analytics/data/analytics.db?mode=ro', uri=True)
rows = db.execute("""
    SELECT v.device_id, v.ts, v.id, v.event_name FROM v_events v
    JOIN v_players p ON p.device_id = v.device_id
    WHERE p.first_date BETWEEN ? AND ? ORDER BY v.device_id, v.ts, v.id""", (since, until))
after_first_end = {}
for device, evs in itertools.groupby(rows, key=lambda r: r[0]):
    evs = list(evs)
    i = next((k for k, e in enumerate(evs) if e[3] == '<match_end>'), None)
    if i is not None:
        nxt = evs[i + 1] if i + 1 < len(evs) else None
        after_first_end[device] = (nxt[3] if nxt else '(no more events)',
                                   nxt[1] - evs[i][1] if nxt else None)
```

The last event of a device that never returned says where it left. An event that
arrives as the very last thing (e.g. results screen opened) means the app was
backgrounded there: AppMetrica flushes on background, so this is reliable.

## 7. Last event per churned device

```sql
WITH last AS (   -- bare column from the MAX row; ties within one second pick one of them
  SELECT device_id, MAX(ts) AS last_ts, event_name AS last_event
  FROM v_events GROUP BY device_id
)
SELECT l.last_event, COUNT(*) AS devices
FROM last l
JOIN v_players p ON p.device_id = l.device_id
LEFT JOIN device_days dd ON dd.device_id = p.device_id AND dd.day > p.first_date
WHERE dd.device_id IS NULL                                  -- never came back
  AND p.first_date < (SELECT MAX(day) FROM device_days)      -- had a chance to come back
  AND p.first_date BETWEEN :since AND :until
GROUP BY 1 ORDER BY 2 DESC;
```

## 8. `040_device_metrics.sql` — one row per device, many questions

```sql
-- device_metrics: per-device facts for research. All devices; filter is_dev in queries.
DROP TABLE IF EXISTS device_metrics;
CREATE TABLE device_metrics AS
WITH days AS (SELECT device_id, COUNT(*) AS active_days FROM device_days GROUP BY device_id),
ses AS (SELECT device_id, COUNT(*) AS sessions, SUM(active_sec) AS active_sec
        FROM sessions GROUP BY device_id),
core AS (
  SELECT device_id,
         SUM(event_name = '<match_start>') AS matches_started,
         SUM(event_name = '<match_end>')   AS matches_finished
  FROM v_events GROUP BY device_id
),
ads AS (
  SELECT appmetrica_device_id AS device_id, COUNT(*) AS ad_impressions,
         SUM(ad_revenue) AS ad_revenue            -- column name: PRAGMA table_info(ad_revenue_events)
  FROM ad_revenue_events GROUP BY 1
)
SELECT d.device_id, d.first_date, d.first_version, d.first_country, d.source_class,
       d.is_dev, d.dev_reason,
       COALESCE(days.active_days, 0)     AS active_days,
       EXISTS (SELECT 1 FROM device_days x
               WHERE x.device_id = d.device_id AND x.day = date(d.first_date, '+1 day')) AS d1,
       COALESCE(ses.sessions, 0)         AS sessions,
       COALESCE(ses.active_sec, 0)       AS active_sec,
       COALESCE(core.matches_started, 0) AS matches_started,
       COALESCE(core.matches_finished, 0) AS matches_finished,
       COALESCE(ads.ad_impressions, 0)   AS ad_impressions,
       COALESCE(ads.ad_revenue, 0)       AS ad_revenue
FROM devices d
LEFT JOIN days ON days.device_id = d.device_id
LEFT JOIN ses  ON ses.device_id  = d.device_id
LEFT JOIN core ON core.device_id = d.device_id
LEFT JOIN ads  ON ads.device_id  = d.device_id;
CREATE UNIQUE INDEX device_metrics_id ON device_metrics(device_id);
```

If the game also sends a per-impression revenue event (an `AdImpression`-style client
event), sum it too and compare with `ad_revenue_events` per day; they should agree to the
cent. A mismatch means lost events or double reporting.

Country tiers are a project decision: keep them in a model table
(`country_tiers(country, tier)`) and join it, never inline long `IN (...)` lists in queries.

## 9. Distributions, medians, concentration

SQLite has no MEDIAN:

```sql
WITH x AS (
  SELECT active_sec AS v,
         ROW_NUMBER() OVER (ORDER BY active_sec) AS rn,
         COUNT(*) OVER ()                        AS n
  FROM device_metrics
  WHERE is_dev = 0 AND first_date BETWEEN :since AND :until
)
SELECT MIN(n) AS devices, AVG(v) AS median_sec FROM x WHERE rn IN ((n + 1) / 2, (n + 2) / 2);
```

Buckets for a histogram: `CASE WHEN active_sec < 60 THEN '<1 min' WHEN ... END`.

Revenue concentration (top payers' cumulative share):

```sql
WITH r AS (
  SELECT ad_revenue, ROW_NUMBER() OVER (ORDER BY ad_revenue DESC) AS rn,
         SUM(ad_revenue) OVER () AS total
  FROM device_metrics WHERE is_dev = 0 AND ad_revenue > 0
)
SELECT rn, ROUND(ad_revenue, 3) AS revenue,
       ROUND(100.0 * SUM(ad_revenue) OVER (ORDER BY rn) / total, 1) AS cum_share_pct
FROM r WHERE rn <= 10;
```

Revenue by day of life (does the cohort keep earning after day 0?):

```sql
SELECT CAST(julianday(r.date) - julianday(p.first_date) AS INTEGER) AS life_day,
       COUNT(*) AS impressions, ROUND(SUM(r.ad_revenue), 2) AS revenue
FROM ad_revenue_events r JOIN v_players p ON p.device_id = r.appmetrica_device_id
WHERE p.first_date BETWEEN :since AND :until
GROUP BY 1 ORDER BY 1;
```

## 10. Project query file

```sql
-- D1 by first day and source class, players only
-- params: :since, :until — first-day window, app time zone
SELECT p.first_date, p.source_class, COUNT(*) AS devices, ...
FROM v_players p ...
```

The first line is the title shown by `query list`. One question per file; name it for
the question (`first_session_funnel.sql`, `d1_by_source.sql`).

---

Sections 11–19 are the building blocks of a **full review** (the analytics-research
playbook 0). 11–12 feed the engine's standard tables; the rest are patterns to adapt.

## 11. New players and key metrics (`ga.py keymetrics`)

The key-metrics table of every report comes from the engine, one column per first version:

```
py analytics/ga.py keymetrics --since 2026-09-08 --until 2026-09-21 [--players v_new_players] [--life-days 7]
```

Players = `v_players` by default. When "first seen in the window" is not "new" (the window
starts mid-life of the game), give the model a view of new players and pass it:

```sql
-- v_new_players: players whose first event in the database is their install day
DROP VIEW IF EXISTS v_new_players;
CREATE VIEW v_new_players AS
SELECT p.device_id FROM v_players p
WHERE p.first_dsr = 0;          -- e.g. days-since-install parameter at the first event;
                                -- or: install row of the device inside the window
```

Rows and their definitions are printed under the table (`--format html` puts them in the
table note). Sessions are the SDK's `session_id`: if a session breaks on every
backgrounding in this game (an interstitial included), say so in the method and add the
launch-based numbers from the model next to the table; do not silently replace the rows.
`--life-days 7` makes versions of different age comparable (activity of life days 0–6 only).

## 12. Steps for the drop-off table (`ga.py dropoff --steps`)

The drop-off table has two parts: ordered steps (loading, FTUE, the first core action),
then every 30 s of active time. The steps are the project's: a view with `device_id,
step_no, step_name` — one row per step a device reached, any number of rows per device (the
engine takes each device's furthest step, so a lost event does not break the chain).
Names are shown in the report, so write them in the report language.

```sql
-- 045_steps.sql: loading and tutorial steps for ga.py dropoff --steps v_first_steps
DROP TABLE IF EXISTS step_map;
CREATE TABLE step_map (event_name TEXT, step TEXT, step_no INTEGER, step_name TEXT);
INSERT INTO step_map VALUES
  ('<game_loading>', '<init analytics>', 1, 'Загрузка: аналитика'),
  ('<game_loading>', '<init ads>',       2, 'Загрузка: реклама'),
  ('<game_loading>', '<scene loaded>',   3, 'Загрузка: первая сцена'),
  ('<ftue>',         '<choose hero>',    4, 'Обучение: выбор персонажа'),
  ('<ftue>',         '<first purchase>', 5, 'Обучение: первая покупка');

DROP VIEW IF EXISTS v_first_steps;
CREATE VIEW v_first_steps AS
SELECT DISTINCT v.device_id, m.step_no, m.step_name
FROM v_events v
JOIN step_map m ON m.event_name = v.event_name AND m.step = v.<step_param>;
```

```
py analytics/ga.py dropoff --since D --until D --steps v_first_steps [--players v_new_players]
py analytics/ga.py dropoff ... --scope first-day        # only the first day's activity
py analytics/ga.py dropoff ... --version 0.2.0          # one build; run once per build to compare
```

Add a `sec` column (how long the step took, e.g. a `step_time` parameter; NULL where
unknown) and the same table shows the loading time per step: median · p90 · max.

A step that is not an event but a condition (reached the first scene, bought anything) is
a `UNION ALL` branch of the same view. Check the chain on raw sequences of a few devices
before trusting it: an event sent once per launch, not once per install, still counts once
per device here.

## 13. Loading time by step

Per step: devices, average, median, p90, max seconds; plus the share whose first launch
ends inside loading. Averages are ruined by backgrounded loads (thousands of seconds), so
the median and p90 carry the message; show the max only to prove the outliers exist.

```python
import sqlite3, statistics
db = sqlite3.connect('file:analytics/data/analytics.db?mode=ro', uri=True)
rows = db.execute("""
    SELECT v.<step_param>, CAST(REPLACE(v.<step_time>, ',', '.') AS REAL)
    FROM v_events v JOIN v_new_players n ON n.device_id = v.device_id
    WHERE v.event_name = '<game_loading>' AND v.<launch_no> = 1""").fetchall()
by_step = {}
for step, sec in rows:
    if sec is not None:
        by_step.setdefault(step, []).append(sec)
for step, xs in by_step.items():
    xs.sort()
    p90 = statistics.quantiles(xs, n=10)[-1] if len(xs) >= 10 else max(xs)
    print(step, len(xs), round(statistics.mean(xs), 2), round(statistics.median(xs), 2), round(p90, 2), max(xs))
```

## 14. Core actions by their number in the session

For each core action (buy, sell, steal, lose, win…): how many devices do it a 1st, 2nd,
… Nth time within one session, and when (median seconds into the session). The curve shows
where the loop stops pulling players forward. The engine computes it:

```
py analytics/ga.py ordinals --events <buy>,<steal>,<sell> --players v_new_players
py analytics/ga.py ordinals --actions v_core_actions      # device_id, session_id, ts, label [, sec]
```

A view is needed when an action is a parameter value, or when the project's session unit is
not the SDK session (a launch number from the payload). The SQL below is what it does.

```sql
WITH a AS (
  SELECT v.device_id, v.session_id, v.event_name,
         ROW_NUMBER() OVER (PARTITION BY v.device_id, v.session_id, v.event_name
                            ORDER BY v.ts, v.id) AS nth,
         v.ts - MIN(v.ts) OVER (PARTITION BY v.device_id, v.session_id) AS sec_in_session
  FROM v_events v JOIN v_new_players n ON n.device_id = v.device_id
  WHERE v.event_name IN ('<buy>', '<sell>', '<steal>', '<lost>')
)
SELECT event_name, nth, COUNT(*) AS events, COUNT(DISTINCT device_id) AS devices
FROM a WHERE nth <= 25 GROUP BY 1, 2 ORDER BY 1, 2;
```

Medians per `(event_name, nth)` in Python from the same rows (`statistics.median` of
`sec_in_session`). If the game sends its own play-time counter in the payload, prefer it
over the wall clock (the wall clock includes backgrounded time). Report: devices reaching N,
% of the cohort, median time. Use the project's session unit (§11).

## 15. Leaving after negative events

What share of players background the app or end the session within 20 s of a negative
event (lost an item, got hit, lost a match, an interstitial started), and how many come
back. Compare with the same share after a neutral event to see what is normal. The engine
computes it:

```
py analytics/ga.py leaving --events <item_lost>,<got_hit>,<interstitial_started>,<purchase> \
    --pause "SELECT device_id, ts FROM v_events WHERE event_name = '<app_focus>' AND has_focus = 'False'" \
    --resume "SELECT device_id, ts FROM v_events WHERE event_name = '<app_focus>' AND has_focus = 'True'" \
    --ignore <app_focus>,<heartbeat> --players v_new_players
```

`--pause` / `--resume` take event names when the game sends separate events. The SQL below
is the idea behind it.

```sql
WITH e AS (
  SELECT v.device_id, v.session_id, v.ts, v.event_name,
         LEAD(v.event_name) OVER w AS next_event,
         LEAD(v.ts)         OVER w AS next_ts,
         LEAD(v.session_id) OVER w AS next_session
  FROM v_events v JOIN v_new_players n ON n.device_id = v.device_id
  WINDOW w AS (PARTITION BY v.device_id ORDER BY v.ts, v.id)
)
SELECT event_name AS trigger,
       COUNT(DISTINCT device_id)                                              AS devices,
       COUNT(*)                                                               AS events,
       SUM(next_event = '<app_pause>' AND next_ts - ts <= 20)                 AS paused_20s,
       SUM(next_ts IS NULL OR (next_session IS NOT session_id AND next_ts - ts > 20)) AS left_session,
       SUM(next_ts IS NULL)                                                   AS never_came_back
FROM e
WHERE event_name IN ('<item_lost>', '<got_hit>', '<match_lost>', '<neutral_event>')
GROUP BY 1;
```

With a pause/resume event pair (`OnApplicationPause`-style) the next event after the pause
tells whether they returned; without it, a session that ends within 20 s is the signal
(AppMetrica flushes on background). An interstitial backgrounds the app by itself: for
"interstitial started" count only pauses that do not end with the ad's own close event.

## 16. Economy: sources and sinks

```sql
SELECT direction, source, COUNT(*) AS events, COUNT(DISTINCT device_id) AS devices,
       SUM(amount) AS amount, 1.0 * SUM(amount) / (SELECT COUNT(*) FROM v_new_players) AS per_player
FROM v_currency c JOIN v_new_players n USING (device_id)      -- the project's ledger view
GROUP BY 1, 2 ORDER BY 1, amount DESC;
```

Show what players earn and spend per minute of active time, the balance over the first
10 minutes (median per 30-s bucket), and what the prices mean in minutes of earning.
Duplicated ledger events (one income sent twice) double every number here — check §18 first.

## 17. Ads by placement and format

`ad_revenue_events` often lacks the placement; the client ad event usually has it:

```sql
SELECT <placement>, <format>, COUNT(*) AS impressions, COUNT(DISTINCT device_id) AS devices,
       ROUND(SUM(<revenue>), 4) AS revenue, ROUND(1000.0 * SUM(<revenue>) / COUNT(*), 2) AS ecpm
FROM v_ads GROUP BY 1, 2 ORDER BY revenue DESC;
```

Per player = impressions / cohort players (not / devices that saw the ad). Rewarded:
offered vs shown vs completed where tracked. Reconcile the client total with
`ad_revenue_events` per day before quoting either.

## 18. Technical checks (block 4)

```sql
-- exact duplicates: same device, event, second and payload
SELECT event_name, COUNT(*) - COUNT(DISTINCT appmetrica_device_id || '|' || event_timestamp || '|' || COALESCE(event_json, ''))
       AS duplicate_rows, COUNT(*) AS rows
FROM events GROUP BY 1 HAVING duplicate_rows > 0 ORDER BY duplicate_rows DESC;

-- payloads that are not JSON
SELECT event_name, COUNT(*) FROM events WHERE event_json_raw IS NOT NULL GROUP BY 1;

-- client vs server ad revenue per day
SELECT a.date, a.server, c.client FROM
  (SELECT date, ROUND(SUM(ad_revenue), 4) AS server FROM ad_revenue_events GROUP BY 1) a
  LEFT JOIN (SELECT day AS date, ROUND(SUM(<revenue>), 4) AS client FROM v_ads GROUP BY 1) c USING (date);
```

Constant and empty parameters: `py analytics/ga.py catalog --format md` (distinct values =
1, numeric share, sample values). Errors and crashes: share of devices with any, top groups,
first session vs later. For each defect write which metric it biases and in which direction.

## 19. Countries (block 5)

```sql
SELECT COALESCE(m.first_country, '?') AS country, COUNT(*) AS players,
       ROUND(100.0 * AVG(m.d1), 1) AS d1_pct,
       ROUND(AVG(m.active_sec) / 60, 1) AS active_min_mean,
       ROUND(AVG(m.ad_revenue), 4) AS arpu,
       ROUND(100.0 * SUM(m.ad_revenue) / (SELECT SUM(ad_revenue) FROM device_metrics WHERE is_dev = 0), 1) AS revenue_share
FROM device_metrics m JOIN v_new_players n USING (device_id)
GROUP BY 1 ORDER BY players DESC LIMIT 12;
```

D1 only over devices whose next day is complete (§4); medians of active time from Python;
the rest of the countries as one "other" row. `ga.py keymetrics --by country` gives the
same key metrics with countries as columns.
