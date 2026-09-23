# Pitfalls: trap → symptom → rule

Each of these produced a wrong or misleading number in a real report.

## Data and time

| Trap | Symptom | Rule |
| --- | --- | --- |
| Incomplete recent days | the last day shows a drop; a day pulled early was missing a quarter of its events and kept gaining rows on later syncs | today is always incomplete; data arrives up to 7 days late — mark the last ~7 days preliminary, D1/DN only for cohorts whose day N is over |
| Different clocks | AppMetrica day totals never match Google Ads, AdMob or GA4 | AppMetrica = app time zone, Google Ads = account zone, AdMob = Pacific by default, GA4 = property zone; compare over whole windows, re-bucket by Unix timestamp if a day matters, say which clock |
| Stale model tables | numbers do not move after a sync | model tables are snapshots: `model apply` after every sync |

## Population

| Trap | Symptom | Rule |
| --- | --- | --- |
| Device ≠ player | "users" inflated by reinstalls and second phones | the unit is the device unless `profile_id` is set; say "devices" |
| Developer devices left in | "organic" doubled before a campaign; the only successful purchases and all restores came from team phones | exclude devices from team countries, devices that ever ran an unpublished version, and extreme reinstallers (one team phone reinstalled 13×) — through the model (`v_players`), never ad hoc |
| Attribution not checked | a report claimed "no organic traffic at all" | read `installations` (`publisher_name`, `tracker_name`) → paid / organic / unknown before any traffic claim |
| Network vs attributed counts | 237 console installs vs 159 attributed | part of paid appears as organic/`unknown` the same days; paid-period organic is not clean |
| Cohort by install row | versions and countries wrong for late or repeated install rows | cohort = first event: day, version, country |
| First seen in the window = new | a window starting mid-life counts old players as new: their "first day" D1 and time look like veterans' | if events carry days since install (or the install row is in the window), define new players by it in the model and pass them as `--players` |
| Geo mixed into channel or build comparisons | paid "better" than organic; build "worse" | split by country tier first. US paid vs US organic: D1 12.6 % vs 11.1 %, ARPU $0.038 vs $0.042; non-US organic D1 0 %, ARPU 12× lower |
| Small samples | a 5–7 pp "effect" flips next week | 40–70 devices per cohort is normal; claim an effect only if several-fold or repeated in independent slices; n next to every rate |

## Metrics

| Trap | Symptom | Rule |
| --- | --- | --- |
| Session span as play time | average session 389 min | active time = sum of gaps inside a session, each capped at 600 s |
| SDK session = launch | an AppMetrica session restarts on every backgrounding, an interstitial included: "sessions per player" and "stuck in loading" doubled | check what breaks a session in this game; when it breaks on ads, count launches (a start-of-loading event) for launch metrics and say which unit the key-metrics table uses |
| Heartbeat build | new build "plays longer" | a periodic event (every 30 s in a match) changes the measurement; state the bias direction or compare on common events |
| Mean only | "12 minutes per player" while the median player played 5 minutes and 1 match | median + distribution beside every mean |
| Revenue mean | ARPU driven by 5 of 39 devices (67 %), median $0.04 vs mean $0.13; some "whales" are lucky $0.2–0.3 impressions on flagship phones | show top-N share and median |
| Waiting for LTV to ripen | decisions postponed for weeks | check the life-day curve: 70–80 % of ad revenue arrived on day 0, 88 % by D1 — day-0 ARPU was the LTV |
| One funnel step for two things | total completion unchanged, so "the build did nothing" | "finished the first match" and "started a second" are separate steps (53 % → 76 % finish while second-start fell 79 % → 60 %) |
| Guessing where people leave | "they quit in the match" without evidence | last event per churned device; an event that arrives last means the app was backgrounded there (AppMetrica flushes on background) |
| Aggregates before sequences | a plausible total built on a wrong assumption (which mode a level was in) | read raw sequences of a few devices first; verify load-bearing numbers independently |

## Ads telemetry

| Trap | Symptom | Rule |
| --- | --- | --- |
| Timeout guard across an ad pause | 346 "show_timeout" failures; 342 had an impression in the same second | verify failures against impression events before believing them |
| Latency that is view duration | "loading takes 15–30 s" | read where the timer stops; a `wait_sec` sent after returning from the ad measures viewing |
| Dead constant fields | slicing by `AdTypeCount` (always 0) or `Network` (always "Admobe") | report them as dead; do not slice |
| High CTR | interstitial CTR 13.7 %, one network 70 % | likely accidental clicks at a navigation tap; the network may limit traffic |
| Collapsed failure reasons | two "reasons" that are one outcome; a reason carrying the previous attempt's state | read the code that sets the reason before counting by it |

## External numbers

| Trap | Symptom | Rule |
| --- | --- | --- |
| Conversions as installs | CPI "$0.15" vs real $0.40 per player | real CPI = spend / attributed players who opened the game |
| Console ROAS | value/cost 3.87 vs real revenue 1/11 of stated value | check which actions carry value and where it comes from |
| Screenshot without range | an AdMob screenshot could not be matched to any window | every screenshot needs its date range and filters; ask |
| Organic blamed on the build | organic −2.5× on a release day in every country, before the build was served | check store-side causes (listing, ranking, reviews) and rollout timing |
