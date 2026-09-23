# End-to-end test log

Real runs of fresh agents on real projects, following docs/TESTING.md. Each entry: what was
asked, what worked, what broke, what changed in the kit because of it. Projects are
anonymised; business metrics of the test games are left out.

## 2026-09-21 — a Unity idle game (AppMetrica, ~380 installs/day, ~500k events/day)

Skill discovery: `codex exec` (0.150.1, `-m gpt-5.6-sol`) and `claude -p` (2.1.168) both list
all seven skills from `.agents/skills` and `.claude/skills`.

| Run | Agent | Ask | Outcome | Kit change |
| --- | --- | --- | --- | --- |
| 1a | Claude `-p` | connect + model, 30 days | SDK key found in the activator component, app resolved, toml filled; sync started in the agent's own background and died when the headless run ended | 0.1.1: `sync --background` (detached, outlives the agent) + `sync --wait` |
| 1b | Claude `-p` | connect + model, 14 days | protocol followed (`apps` → toml → dry run → `--background` → `--wait`); one 7-day `events` chunk = 1.4 GB CSV, database hit 5.6 GB + 5.7 GB WAL at 600k of 3.5M rows — stopped by the lead | 0.2.0: device sampling, `--no-flatten`, disk guard, WAL checkpoint, volume probe in the connect skill |
| 1c | Claude `-p` | same | probed one day (~616k events), chose `sample = 0.05` and `flatten_params = false` by the skill's tiers, wrote the reason into the toml; then ran `--wait` with a 540 s timeout, Claude's 2-minute command limit backgrounded it, the agent scheduled a wake-up and ended | 0.2.1: `--wait` returns after 90 s; skills forbid handing the wait to the environment |
| 1d | Claude `-p` | wait for the running sync + model | loaded the data-model skill (the wait rule lived only in connect) and again scheduled a wake-up | 0.2.2: the wait rule in the kit conventions and data-model preconditions; `ga.py` warns when run from `analytics/`; `--wait` recaps the log tail instead of replaying it |
| — | lead | finish the sync | 14 days in 14 min: 366,743 of 6.6M events kept (5 %), database ~200 MB | — |
| 1e | Claude `-p` | build the model | 7 model files + 5 queries + a 131-line `notes/project.md`; found that the game wraps most payloads under a numeric key = session ordinal; `v_events` = `events`, D1 equal to the kit's `retention` query, `v_ad_revenue` = `ad_revenue_events` to the cent; asked the owner for dev devices and the status of an old build. 10 min, 50 turns | — |
| 2 | Codex `exec` (`gpt-5.6-sol`) | tracking audit + report | picked `analytics-project-audit` + `analytics-report` by itself; `reports/tracking-audit/v001` built with the kit theme (tiles, short answers, hbar chart, tables, cards, data requests), index rebuilt, notes and findings updated. Found real defects: two-thirds of the stream are duplicate income events, a session-time field always 0, an A/B variant label unstable per device, ad revenue without placement/unit, every IAP failure logged as `cancel`; 0 of 12 coverage areas complete. Checked its own render at 400/500 px. ~10M input tokens (mostly cached), 39k output | — |
| 3 | Claude `-p` | «где теряем новых игроков в первой сессии и сколько приносит игрок с рекламы» | research skill end to end in 17 min: plan → per-device tables → verification script (`work/verify.py`, `claims.md`, all numbers matched) → `reports/first-session-and-ad-arpu/v001` with 4 charts, tables, actions, data requests, method; findings logged. Found a share of new players stuck in loading behind the ads SDK / Remote Config wait and that ~80 % of ad revenue arrives on day 0. Could not publish an Artifact headless (said so, as the skill asks); the lead published it | 0.2.3: tiny money values printed as `$0,00` in chart labels — formatting now adds decimals until a non-zero value shows |

Owner review after run 3: the conclusions were right, but every report was organised
differently (title-thesis, own section order), and the key tables a studio analyst always
shows — base metrics by build, drop-off by steps and by 30 s — were missing or ad hoc →
0.3.0: one seven-block skeleton checked at build, the title is the request, `keymetrics` and
`dropoff` in the engine.

## 2026-09-22 — the same game, a full review (kit 0.3.0)

Skill discovery after the update: `codex exec` (0.150.1, `-m gpt-5.6-sol`) lists all seven
skills with the new descriptions.

| Run | Agent | Ask | Outcome | Kit change |
| --- | --- | --- | --- | --- |
| 4 | Claude `-p` (2.1.168) | «Сделай полный анализ игры за последние две недели» | 14.9 min, 59 turns, $5.0. research → report skills; `report new --kind full`, the title is the request (period and build, but without the game's name); all seven blocks with the `keymetrics` and `dropoff` tables embedded; a steps view added to the project model, not to a scratch script; 5 hypotheses with evidence links, tests and thresholds, 5 recommendations each linked to one; 18 load-bearing numbers recomputed by an independent script, all matched; the build passed the skeleton check on the first attempt; findings and notes updated. Against a studio analyst's review of an earlier build: the same reading of loading and tutorial (losses now small), rewarded ads under-used, passive income dominating the economy, the main loss between days rather than inside the session; new — the bots' threat is now weak (the analyst had asked to tone it down). Missed from the default set: loading step times, core actions by their number in the session, leaving within 20 s after negative events ("needs sequence work"); the key-metrics table counted players first seen in the window while the text used new players; step names in English in a Russian report; a 5-device build got its own column; zero money printed as `$0,0000`; ISO dates in the eyebrow | 0.3.0 before release: `ga.py ordinals`, `ga.py leaving` (pause/resume as events or as flag rows, `--ignore` heartbeats), a `sec` column in the steps view adds step time to the drop-off table, `keymetrics --min-devices`, `$0`, `{{meta:window}}`; skills: one population for the whole report, the title form «Game version, period: request», step names in the report language, the four standard tables in the research workflow |

Lessons that became rules:

- A headless run is not resumed. Anything long must be a detached process, and the agent must
  wait in the foreground in short calls.
- Measure before pulling. Event volume varies 100× between games; a one-day probe decides the
  sample rate before a week is downloaded.
- Parameter flattening is the storage hog (~6 KB per event with indexes); it is optional now.
- An SDK session is not a launch: in this game a session restarted on every backgrounding
  (an interstitial included), which doubled "stuck in loading" until the model counted launches.
- What the default set lists but the engine does not compute gets skipped under time pressure
  (run 4 skipped three of the twelve items). Standard tables belong in the engine, where every report
  gets them the same way.
