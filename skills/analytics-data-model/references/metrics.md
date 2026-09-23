# Metric definitions

Definitions that held up on a real indie mobile game. Use them unless
`analytics/notes/project.md` records a different project decision. When you define a
metric differently, write the definition into the notes and the report's method section.

## Units and populations

- **Device** — the unit of analysis (`appmetrica_device_id`). `profile_id` is empty unless
  the client sets it; one human with two phones is two devices; a reinstall may be a new
  device. Say "devices" or "players (devices)" in reports, not "users", unless a profile
  id exists.
- **Players** — devices with `is_dev = 0` (`v_players`). Every rate is over players.
- **New device / cohort** — grouped by the device's **first event**: first day, first
  version, first country. Not by the install row (install rows can be late, repeated, or
  missing).
- **Complete day** — a day that is over in the app's time zone. The last ~7 days can
  still grow through late delivery; mark them preliminary.

## Retention

- **D1** — the device has any event on the calendar day after its first day. **DN** —
  any event on first day + N. Compute DN only for cohorts whose day N is over.
- "Returned within N days" (any day 1..N) is a different metric; name it explicitly.
- Always print the n: `D1 12.6 % (n = 159)`.

## Time in game

- **Active time** — per session, sum of gaps between consecutive events inside one
  `session_id`, each gap capped at 600 s; per device, sum over sessions.
- **Session span** (last − first event) is not play time: a backgrounded app inflated
  averages to hundreds of minutes. Use it only to show that it is broken.
- A build that adds a periodic event (heartbeat, match tick) changes the measurement:
  quiet stretches previously capped now count fully, so that build looks longer. When
  comparing builds, say which way the bias goes, or compare on events both builds send.

## Distributions over means

- Report the median and a distribution (buckets or percentiles) next to any mean. Real
  case: the mean said 12 minutes, the median new player played 5 minutes and 1 match.
- Revenue is concentrated: 5 of 39 users gave 67 % of revenue; median $0.04 vs mean
  $0.13. Some "whales" are lucky impressions on flagship phones ($0.2–0.3 for one
  impression). Show top-N cumulative share and the median.

## Funnels

- **By device**, ordered, each step counted once per device: loaded → menu → chose mode
  → started match → finished match → 2nd → 3rd → 5th match → D1 (adapt to the game's core
  loop).
- "Finished the first match" and "started a second one" are separate steps. A build can
  move the loss from one to the other without changing the total (real case: first-match
  completion 53 % → 76 %, but starting a second match after finishing fell 79 % → 60 %).
- Report count, % of the first step, % of the previous step, and n.

## The first core loop

- **What happens right after the first match / level** is the most informative single
  slice: next action (continue, menu, restart, rewarded ad, app closed) and time spent on
  the results screen before it.
- **Last event per churned device** shows where people leave. An event that arrives as the
  very last thing (results screen opened) means the app was backgrounded there —
  AppMetrica flushes on background, so this is reliable.

## Revenue

- **Ad revenue per device** — sum of per-impression revenue from `ad_revenue_events`, or
  from a client impression event carrying revenue (`AdImpression`-style); the two agreed
  to the cent when both worked. Disagreement = lost or duplicated events.
- **IAP revenue per device** — from `revenue_events`; check that order ids look real and
  that test purchases come only from dev devices.
- **ARPU** — revenue of a cohort / devices in the cohort (state the window: day 0, D7,
  to date). **ARPDAU** — revenue of a day / active devices that day.
- **LTV ≈ install day** for ad-monetized casual games: 70–80 % of a cohort's ad revenue
  arrived on day 0 and 88 % by D1. Check the life-day curve in this project before
  waiting for cohorts to "ripen"; if it is flat after day 0, day-0 ARPU is the LTV.

## Ads

- **Impressions per device** by format (interstitial, rewarded, banner).
- **eCPM** = revenue / impressions × 1000, by country tier. Observed: US interstitial
  ~$29–31, US rewarded $55–100, rest of world $3–4. A country-mix change moves blended
  eCPM without anything else changing.
- **Rewarded show rate** = shown / offered (or loaded vs shown). 8 % means the inventory
  sits idle: players are not offered or do not want the reward.
- **Rewarded funnel**: offered → clicked → ready? → shown → completed / failed by reason.
- **Interstitial frequency** — impressions per session or per core loop vs the cooldown
  ceiling (how many the rules allow).
- **CTR** — clicks / impressions per format and network. Very high interstitial CTR
  (13.7 %, one network 70 %) suggests accidental clicks — the ad appearing under the
  finger at a navigation tap — and the network may limit traffic for it.

## Paid acquisition (details in the analytics-import-external skill)

- **Real CPI** = spend / paid devices that opened the game (AppMetrica attribution), not
  spend / console "conversions".
- **ROI of a cohort** = revenue of the cohort / spend. **Break-even ARPU** = CPI
  (required ARPU = CPI × target ROAS).

## Match / level telemetry worth having

Start; end with result, reason and placement; quit — distinguishing quitting a running
match from leaving the results screen; restart with reason; a periodic tick (elapsed
time, HP, opponents alive); per-match stats (FPS average and minimum, slow-frame share,
damage split, time to first damage / first kill, progress %); device RAM. Without these,
"why do they leave the match" can only be guessed.

## Sample size

40–70 devices per cohort is normal for an indie game. A 5–7 pp difference at that size is
noise. Call something an effect only when it differs several-fold or repeats in
independent slices (other days, other countries, other sources). Put n next to every rate.
