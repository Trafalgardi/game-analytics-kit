# Field knowledge — source material for the skills

Everything below was learned the hard way on a real mobile game (Unity, Android, AppMetrica +
Firebase + AdMob mediation, Google Ads app campaigns) between August and September 2026.
Each item states the trap, how it showed up, and the rule that avoids it. Skills turn these
into instructions; nothing here is specific to that game unless marked *(example)*.

---

## A. AppMetrica Logs API

- **Contract.** `GET https://api.appmetrica.yandex.ru/logs/v1/export/<table>.csv?application_id=&date_since=YYYY-MM-DD HH:MM:SS&date_until=...&date_dimension=default&fields=a,b,c` with `Authorization: OAuth <token>`, `Accept-Encoding: gzip`. `date_dimension=default` filters by event time, `receive` by server receive time. `skip_unavailable_shards=true` thins the answer instead of failing it.
- **Statuses.** 200 = CSV ready; 202 = being prepared (body says `Progress is N%`), poll again; 429 = three exports already queued for this app, wait `Retry-After`; 400 `Try to use more parts.` = day too big, retry with `parts_count=N&part_number=K`; 401 = missing or expired token.
- **The numeric application_id is not the SDK key.** Get it from `GET /management/v1/applications` (fields `id`, `name`, `api_key`, `create_date`, `time_zone_name`) and match `api_key` with the key found in the game code (e.g. `AppMetricaActivator`, `AppMetrica.Activate(new AppMetricaConfig("<key>"))`).
- **Token.** OAuth token of the Yandex account with `appmetrica:read`. The owner creates an app at https://oauth.yandex.ru/client/new (platform "Web services", redirect `https://oauth.yandex.ru/verification_code`, scope AppMetrica → `appmetrica:read`), then opens `https://oauth.yandex.ru/authorize?response_type=token&client_id=<ClientID>` and copies `access_token` from the address bar. One token serves every app of that account. Never print it, never commit it, never write it into the database.
- **Tables worth pulling:** `events`, `sessions_starts`, `installations`, `crashes`, `errors`, `revenue_events`, `ad_revenue_events`. Others (`clicks`, `postbacks`, `push_tokens`, `profiles`, `deeplinks`, `ecommerce`) rarely matter.
- **Ranges, not days.** Report preparation is queued and sequential; a 1-day request waits about as long as a 7-day one. Pull 7-day chunks; while one downloads, request the next (warm-up) — at most 3 exports queued per app.
- **Replace by range.** Rows have no id. Delete the chunk's days and insert inside one transaction. Hash-dedup would merge genuine duplicates (two identical events in one second).
- **Late delivery up to 7 days.** Days younger than that are re-pulled, but not more often than every ~12 h (quota). Today is always incomplete.
- **Parse from a file.** Reading CSV straight from the HTTP stream broke (`I/O operation on closed file`); download to a temp file first.
- **SQLite in autocommit**, explicit `BEGIN IMMEDIATE` per chunk; otherwise the second write fails to start its transaction.
- **Field drift.** The docs lag the API. Drop unknown fields from the request and remember them; a missing column is better than a failed sync.
- **Throughput.** Two weeks × 5 tables ≈ 13 min; 25 days × 7 tables ≈ 60 min, `errors` alone once waited 20 min at 96–98 % "preparing". Sync the tables the question needs; run long syncs in the background.
- **Two syncs into one SQLite file at once** risk "database is locked". If one table is urgent, sync it into a separate scratch db (`--db`) and query both.
- **Game parameters arrive as one JSON string** in `event_json` (flat dictionary). Flatten into `event_params(key, value_text, value_num)` once; `json_extract` over millions of rows is slow.
- **Dates are in the app's time zone** (Management API `time_zone_name`), Google Ads uses the account time zone, AdMob uses Pacific time by default. Day-level numbers from different tools never match exactly; say which clock a number uses.

## B. Data hygiene

- **Unit of analysis is the device.** `profile_id` is empty unless the client sets it. A reinstall is a new "player". One human with two phones is two players.
- **Remove developer and test devices before anything else.** They cluster in the team's countries *(example: NL and RU)*, run unpublished builds, reinstall many times (one device reinstalled 13×), and they are the only ones with successful test purchases. Left in, they doubled "organic" installs and produced the only `iap_success` rows. Rule: exclude devices that ever ran a version not in the published list, devices from the team's countries, and extreme reinstallers; keep the rule in `notes/project.md` and in the model, not in each query.
- **Attribution lives in `installations`:** `publisher_name = 'Google Ads'` → paid; `tracker_name` in (`Google Play`, `Google Search`) → organic; `unknown` → unattributed (in paid periods mostly paid-adjacent). A report once claimed "no organic traffic at all" because nobody looked at this table.
- **Network-side counts exceed ours.** Google Ads reported 237 installs, AppMetrica attributed 159 (67 %). Part of the gap shows up as organic/unknown in the same days.
- **Cohorts by first event, not by install row.** A device's first event gives day, version and country. Compare cohorts only on complete days, and only same geo + same source when judging a build.
- **Geo dominates quality.** US paid vs US organic behaved the same (D1 12.6 % vs 11.1 %, ARPU $0.038 vs $0.042); organic outside the US had D1 0 % and ARPU 12× lower. Always split by country tier before blaming a channel or a build.
- **Small samples.** 40–70 devices per cohort is normal for an indie game. A 5–7 pp difference is noise. Call something an effect only when it differs several-fold or repeats in independent slices; write the n next to every rate.

## C. Metric definitions that held up

- **D1** = the device has any event on the calendar day after its first day. DN only for cohorts that lived N days.
- **Time in game** = sum of gaps between consecutive events inside one `session_id`, each gap capped (600 s). Session "span" (last − first event) is ruined by backgrounded apps (averages of 389 min). Heartbeat events added in one build (every 30 s in a match) make that build look longer — note the bias direction when comparing builds.
- **Report medians and distributions**, not only means: the median new player played 5 minutes and 1 match while the mean said 12 minutes.
- **Funnels by device**: loaded → menu → chose mode → started match → finished match → 2nd → 3rd → 5th match → D1. "Finished the first match" and "started a second" are separate steps; a build can move the loss point from one to the other without changing the total (real case: first-match completion 53 % → 76 %, but starting a second match after finishing fell 79 % → 60 %).
- **What happens right after the first match** is the most informative single slice: next action (continue / menu / restart / rewarded / app closed) and time on the results screen.
- **Last event per churned device** tells where people leave; an event that arrives as the very last thing (e.g. results screen opened) means the app was backgrounded there — AppMetrica flushes on background, so this is reliable.
- **Revenue per device** = sum of ad revenue (`AdImpression`-style client event with per-impression revenue, or `ad_revenue_events`); both agreed to the cent. LTV ≈ install day: 70–80 % of ad revenue arrives on day 0, 88 % by D1. Don't wait for cohorts to "ripen".
- **Revenue is concentrated.** 5 of 39 users gave 67 % of revenue; the median was $0.04 against a mean of $0.13. Some "whales" are just lucky impressions on flagship phones ($0.2–0.3 per impression). Always show the distribution.
- **Ad metrics**: impressions per user by format, eCPM by country tier (US interstitial ~$29–31, rewarded $55–100, rest of world $3–4), rewarded show rate (loaded vs shown — 8 % means the inventory is idle), interstitial frequency vs cooldown ceiling.
- **Match / level telemetry worth having**: start, end with reason and placement, quit (distinguish quitting a running match from leaving the results screen), restart with reason, periodic tick (elapsed, HP, alive opponents), per-match stats (FPS avg/min, slow frame %, damage split, first damage / first kill time, progress %), device RAM.

## D. Ad telemetry traps

- A guard timer on `UnscaledDeltaTime` keeps "running" while a fullscreen ad pauses Unity; on resume the first frame carries all the elapsed time and the guard fires before the SDK's `AdOpened` callback is dispatched → 346 "show_timeout" failures that were real impressions (342 had an ad impression in the same second). Verify "failures" against impression events before believing them.
- A `wait_sec` measured from request to the moment the event is sent (after returning from the ad) measures ad view duration, not load latency.
- Fields that are always constant (`AdTypeCount = 0`, `Network = "Admobe"`) are dead; say so instead of slicing by them.
- High interstitial CTR (13.7 %, one network 70 %) suggests accidental clicks — ads appearing under the finger at a navigation tap; AdMob may limit traffic for it.

## E. Paid acquisition (Google Ads app campaigns)

- **"Conversions" is not installs.** The Conversions column sums every primary conversion action (installs, first opens, in-app events). Real case: 107 conversions at "$0.15" vs 39 attributed players → real cost $0.40 per player, exactly the tCPA target that had been set. Real CPI = spend / players who opened the game (AppMetrica paid devices; cross-check GA4 "first user campaign").
- **"Conv. value / cost" can be fiction.** Conversion actions with default values (e.g. $1 per first_open) showed value/cost 3.87 while real revenue was 1/11 of the stated value. Check which actions carry value and where the value comes from before reading any ROAS in the console.
- **When the strategy changes, the conversion set may change.** On the tROAS day conversions matched players 1:1.
- **tROAS math.** Target ROAS R lets Google bid up to predicted value / R per install. With $0.13 per US player and R = 50 %, the ceiling is ~$0.26 — below the $0.40 the same users cost on tCPA. The only way to win auctions is to find predicted-high-value users; with ~5 valuable users in 39 there is no signal. Result: $54 in one hour (learning phase, budget burst), 38 installs at $1.43, same behaviour as before, ROAS 4–5 %.
- **A 50 % ROAS target is a planned 50 % loss** unless revenue keeps coming after day 0. With LTV = install day, it never does.
- **Break-even table**: required ARPU = CPI × target ROAS. Put it in every UA report.
- **Use small CPI buys as a measuring instrument** (one country, ~$15–20, ~40 fresh players) to compare builds on the first-session funnel, not as a revenue channel, until ARPU ≥ CPI.
- **Organic moves on its own.** Installs from Google Play dropped 2.5× overnight on a release day in every country — the build was not even served yet, so the cause was store-side (listing, ranking, review). Watch organic per day next to paid.

## F. External data — what to ask the owner for

- **Google Ads** (per campaign, per day): cost, **Installs** column, conversions segmented by conversion action, conversion value, bid strategy and target history (when it changed), daily budget, geo, hourly chart for launch days. Goals → Conversions: which actions are primary, value source (from event / default).
- **AdMob** (date range + country filter stated!): by ad unit and by ad source — requests, match rate, matched requests, show rate, impressions, eCPM, estimated earnings, clicks, CTR; ad revenue per user and ARPDAV.
- **GA4 / Firebase**: user acquisition cohorts by first user channel group and by first user campaign (new users, total revenue, average value), with country filter stated.
- **Google Play Console**: Statistics → store listing acquisition per day (visitors, acquisitions, conversion rate) and per country; what changed on the listing and when; Android vitals (ANR rate, crash rate, per version); ratings and reviews.
- **App Store Connect** (iOS): impressions, product page views, conversion, installs by source.
- Screenshots are fine; CSV exports are better. Every screenshot must come with its date range and filters — one AdMob screenshot could not be matched to any range in the data because they were unknown.

## G. Research workflow that worked

1. Restate the question and the decision it serves; list what would change the decision.
2. `status` → refresh only the tables and days the question needs; run long syncs in the background and analyse what is already loaded meanwhile.
3. Read `notes/project.md` and `notes/findings.md` first; never re-derive a known filter or re-litigate an owner decision recorded there.
4. Build per-device tables once (first day, version, country, source, dev flag, metrics), then answer many questions from them.
5. Look at raw sequences of events for a handful of devices before trusting any aggregate.
6. Verify the 5–10 numbers the conclusions rest on with an independent pass (a sub-agent or a second script written from the definitions, not from the first script). In practice this caught a wrong assumption about which mode a level was in.
7. Write the report: answers first, then evidence, then actions, then data requests, then method.
8. Append dated findings to `notes/findings.md` and durable facts to `notes/project.md`.

## H. Report writing that the owner accepted

- **One skeleton for every report** (owner feedback, September 2026: the conclusions were
  right, but each report was organised differently, so neither a reader nor an agent could
  find things in the same place): 1 summary — key-metrics table with build versions as
  columns + short answers; 2 product; 3 revenue; 4 technical; 5 countries; 6 hypotheses;
  7 recommendations; then data requests and method. A narrow question keeps the order and
  blocks 1, 6, 7.
- **The title is the request** — what was asked, about which game, version and period
  *(example: «MyGame 0.2.0, 08–21.09: полный разбор»)*. An earlier rule "a title is a name,
  not a caption" *(example: «Игра на один матч»)* was reversed: the owner looks reports up
  by the question. The figurative thesis moves to the standfirst.
- Facts and interpretation are marked apart; every number in the answers, hypotheses and
  recommendations sits in a table or chart of the evidence blocks.
- Hypotheses are numbered and testable (claim → numbers with a link → metric and threshold
  → confidence); every recommendation names its hypothesis, the expected effect and how to
  measure it.
- "Short answers" block: one row per question the owner asked, direct answer first.
- Every section: a lede sentence, then chart or table, then the interpretation. Every chart has a caption that says what to see.
- Owner screenshots embedded where they are discussed, with a tag (source · filter · date) and a note on what they show and what they do not.
- Caveats as notes next to the number they qualify, not in a disclaimer at the end.
- "Data I need from you" as a checklist with exact console paths.
- Method section: sources, date windows, filters, definitions, sample rate.
- Decimal comma and thin-space thousands for Russian; units always shown ($, %, min).

## I. What a studio analyst puts in a full review *(example)*

A hand-made review of a game build by a studio analyst (a document with tables from the
analytics console, one build, one week) — the shape a studio expects a full review to have:

- **Base metrics table**, one column per build: D1/D3/D7 %, playtime per user, sessions
  per user, average session length, interstitials and rewarded per user (two sources side
  by side), ARPU, revenue, users.
- **Drop-off by steps**: install → each loading step (analytics, ads, remote config, scene)
  → each tutorial step → the first core action; was / lost / %. The ads SDK init and the
  first tutorial purchase were the steps to look at.
- **Loading time per step**: average and max seconds, events and users per step — the max
  exposes backgrounded loads, the average and median the real wait.
- **Drop-off by 30 s of play for the first 10 minutes**: the first 30 s lose the most, then
  a steady loss per interval.
- **Core actions by their ordinal in the session** (1st … 25th purchase, sale, capture, loss,
  defence) with average and median play time at which it happens and the share of users
  who got there — shows where the loop stops pulling.
- **Negative events → leaving**: share that minimised the app within 20 s after losing an
  item, after being hit, after an interstitial started, and the share that came back.
- **Economy**: currency sources and sinks, the inventory filling up over the first 10
  minutes, prices in minutes of earning.
- **Revenue by placement**, dead rewarded placements.
- **Critical places and hypotheses**, grouped by phase (loading, the first 30 s, the first
  1.5 minutes, after 5 minutes), each with a proposed change.

The kit's full review computes the same set (analytics-research playbook 0); the engine
produces the base metrics, drop-off, ordinal and leaving tables so they look the same every
time.
