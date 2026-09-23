# Question playbooks

Each playbook: the decision it serves, data to have, steps, traps, and the tiles block 1 of
a question report usually shows. Adapt event names to the project's model
(`analytics/notes/project.md`). SQL patterns live in the `analytics-data-model` skill's
modeling guide (numbers like §13 below point there); metric definitions in its metrics
reference. Every playbook ends in the same report skeleton (analytics-report).

---

## 0. Full review of a period («полный анализ», «полный разбор игры за две недели»)

**Decision:** what to fix, change or test next across the whole game; the baseline the next
build is compared to.
**Data:** `events`, `sessions_starts`, `installations`, `ad_revenue_events`,
`revenue_events` (`errors`/`crashes` when loaded) for the period plus 7 days after its first
cohort day if D7 matters; the model's `v_players`, `sessions`, `device_days`,
`device_metrics`. Period = what the owner said; "the last two weeks" = the last 14 complete
days.

The default set — compute all of it, report every item in its block even when the answer is
"nothing unusual" (one line, one number):

| Block | Item | How |
| --- | --- | --- |
| 1 | Key metrics by build version: players, D1/D3/D7, active time per player, sessions per player, session length, interstitials and rewarded per player, ARPU, revenue | `ga.py keymetrics` (population = the project's new players) |
| 2 | Retention by first day (D1 line, n) | kit `retention` query / §4 |
| 2 | **Drop-off table**: loading and FTUE steps, then every 30 s of the first 10 minutes of active time — reached / lost / % of previous | `ga.py dropoff --steps <steps view>` (§11–12) |
| 2 | Loading time by step: median, p90, max; share that never reaches the first scene | the steps view with `sec` → the same `dropoff` table (§12–13) |
| 2 | Core actions by their ordinal in the session (1st, 2nd, … purchase / sale / steal / loss / win): devices reaching N, % of cohort, median time into the session | `ga.py ordinals` (§14) |
| 2 | Leaving after negative events (lost an item, got hit, lost a match, an interstitial started) next to a neutral event: share that backgrounds or stops within 20 s, comes back, never returns | `ga.py leaving` (§15) |
| 2 | Economy: currency sources and sinks per player, balance over the first minutes, what players save for | §16 |
| 2 | Distribution of active time and sessions (median, buckets), not only means | §9 |
| 3 | Ads by format, placement, network: impressions, per player, eCPM, revenue; rewarded offers vs views where tracked; purchases (payers, revenue, test purchases removed) | kit `ad_revenue_daily`, §17 |
| 3 | Revenue by life day (does it come after day 0?) and concentration (top-N share, median) | §9 |
| 4 | Technical: duplicated events, constant or empty fields, broken JSON, client vs server revenue, errors/crashes per device, events that cannot be ordered | §18 |
| 5 | Countries: players, D1, active time median, ARPU, eCPM, share of revenue per top country (rest as "other") | §19 |
| 6–7 | Hypotheses from the biggest losses and gaps above; recommendations from the hypotheses | — |

Compare with the previous full review when there is one (findings.md): the same tables,
older period left. **Traps:** the window start cuts into old players (use the project's
new-player rule, not "first seen in the window"); SDK sessions that break on backgrounding;
sampled absolute numbers; heartbeat events inflating active time.

---

## 1. Why don't players stay? («почему игроки уходят», «ретеншн»)

**Decision:** what to fix first to lift D1.
**Data:** `events`, `sessions_starts`, `installations`; `errors`/`crashes` for stability;
model `v_players`, `sessions`, `device_days`, `device_metrics`. Complete cohorts only.

1. D1 by first day with n; then by country tier × source. Is it low everywhere or only in
   one slice (often: non-core geos pull the average down)?
2. First-session funnel by device (loaded → menu → mode → start → finish → 2nd → 3rd →
   5th → D1). Where is the biggest absolute loss?
3. Right after the first core loop: next action (continue / menu / restart / rewarded /
   closed) and time on the results screen.
4. Last event per device that never returned.
5. Distributions: active minutes and core loops per device (median, buckets), not means.
6. Stability: share of churned vs retained devices with errors/crashes in the first
   session; loading times; FPS by device class if tracked.
7. Read 5–10 churned devices' raw sequences end to end.

**Traps:** session span; heartbeat builds; geo mix; the last ~7 days preliminary.
**Block 1 tiles:** D1 (n), median first-session minutes, % finishing the first core loop, the
top leave point with its share.

---

## 2. Did build X change engagement? («что изменилось в новом билде»)

**Decision:** keep, roll back, or iterate the change.
**Data:** events by `app_version_name`; release date and rollout percentages (Play
Console); list of tracking changes in X (git log of analytics code).

1. Establish when X reached players: first day each version appears among players, the
   share of new devices starting on X per day (staged rollouts mean two builds coexist).
2. Compare **new** devices whose first version is X vs the previous version — same
   country tier, same source, comparable days (weekday mix). Updaters are a separate
   population; analyse them separately if at all.
3. Compare the funnel step by step, not only the total: the loss point may move.
4. Check telemetry differences: events added or changed in X (heartbeats inflate time;
   new events cannot be compared; fixed bugs change counts).
5. If samples are small, propose a small paid buy per build as a measuring instrument
   (analytics-import-external, UA economics).

**Traps:** comparing all traffic across a campaign boundary; D1 before day 2 is over;
events that exist only in X.
**Block 1 tiles:** first-core-loop completion old → new (n), second-loop start old → new, D1 old
→ new, active minutes median old → new.

---

## 3. Does paid UA pay back? («закупка окупается?»)

**Decision:** continue, change, or stop buying; the thresholds to resume.
**Data:** Google Ads campaign × day with Installs, conversions by action, conversion
value settings, strategy history (analytics-import-external); `installations`
attribution; `ad_revenue_events` / `revenue_events`; model `device_metrics`.

1. Spend and network installs per day; attributed paid players per day; real CPI.
2. Check "Conversions" vs installs vs players; which actions carry value.
3. Paid cohort ARPU by life day — does revenue continue after day 0?
4. Paid vs organic **within the same country tier** (D1, core loops, impressions, ARPU).
5. ROI = cohort revenue / spend; upper bound with same-days organic credited.
6. Break-even table: required ARPU = CPI × target ROAS vs actual ARPU (n).
7. Organic before / during / after the campaign (halo and shadow).

**Traps:** conversions ≠ installs; default conversion values; clocks; geo; attribution
gap (network > attributed).
**Block 1 tiles:** real CPI, day-0 ARPU (n), ROI, required vs actual ARPU gap.

---

## 4. Where do we lose players in the first session? («где теряем игроков»)

**Decision:** which screen, step or technical issue to fix first.
**Data:** events of the first session (first `session_id` per device); loading steps;
screen flow; errors in the first session; ads shown before the first core loop.

1. Devices with an install row but no game event (lost at loading).
2. Loading step durations (median, p90) and the share that never reaches the menu.
3. Ordered funnel of the first session with % of first and % of previous step.
4. Time between steps (median) — where do people wait or wander?
5. Next action after the first core loop and time on the results screen.
6. Last event of devices whose only session was the first one.
7. Errors / crashes in the first session vs later; interstitials before the first core
   loop.

**Traps:** same-second ordering (use a sequence counter if sent); FTUE events sent per
session; backgrounded apps looking like long waits.
**Block 1 tiles:** % reaching the first core loop, % finishing it, the biggest single drop with
n, median time to the first core loop.

---

## 5. Ad monetization health («реклама», «доход с рекламы»)

**Decision:** placements, frequency, formats, networks to change.
**Data:** `ad_revenue_events`; client ad events (offered, clicked, shown, failed with
reason, impression revenue); AdMob export for the same range and countries.

1. Revenue per device distribution (median, top-N share) and by life day.
2. Impressions per device by format; per session / per core loop vs the cooldown ceiling.
3. eCPM by country tier and format; blended eCPM change = mix change or price change?
4. Rewarded funnel by placement: offered → clicked → ready → shown → completed / failed
   by reason; show rate (8 % = idle inventory).
5. Verify failures against impression events (a guard timer across the ad pause once
   produced hundreds of false timeouts); read what `*_sec` fields really measure.
6. CTR by format and network (accidental clicks).
7. Reconcile with AdMob (Pacific clock, same filters): requests, match rate, show rate,
   earnings.

**Traps:** dead constant fields; collapsed reasons; client vs SDK revenue double counting.
**Block 1 tiles:** ad revenue per device (median and mean, n), impressions per device by format,
rewarded show rate, US vs rest-of-world eCPM.

---

## 6. Did organic change? («органика упала», «органика»)

**Decision:** is it the game, the store, or the campaign?
**Data:** `installations` (source class per day, country); Play Console store listing
acquisitions and visitors per day and country; release, rollout and listing-change
history; ratings and reviews; campaign dates.

1. Organic installs per day by country tier; paid next to it.
2. Mark campaign windows (halo lifts organic; shadow moves paid into organic/unknown).
3. Store funnel: visitors and conversion per day — fewer visitors (ranking, search) or
   lower conversion (listing, rating, reviews)?
4. Align with release and rollout dates: did the change start before the new build was
   even served? (Once organic fell 2.5× overnight in every country on a release day — a
   store-side cause.)
5. Day-of-week pattern and one-off spikes (a featuring, a review).

**Traps:** paid-period organic is not clean; attributed "organic" includes shadowed paid;
small daily counts.
**Block 1 tiles:** organic per day before → after (n days), store conversion before → after,
the dated event that lines up with the change.
