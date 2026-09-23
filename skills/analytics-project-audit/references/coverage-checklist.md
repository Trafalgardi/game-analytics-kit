# Coverage checklist and telemetry traps

Score each item: **covered** (the question can be answered from data today), **partial**
(event exists but lacks a parameter, fires in the wrong place, or only some builds send
it), **missing**, **broken** (sends misleading data). Evidence: `file:line` and counts.

## 1. Identity and install

- [ ] Install / first open: SDK install row (`installations`) and a first-launch event.
- [ ] Profile id / user id set by the client (`profile_id` non-empty) — otherwise every
      metric is per device, reinstalls are new players.
- [ ] User properties: days since install, session count, payer / no-ads owner flag,
      build, A/B group.
- [ ] Dev and test builds distinguishable (separate SDK key, a flag, or a version rule).
- [ ] Consent / opt-out handling documented (which builds or regions send nothing).

## 2. Attribution

- [ ] `installations` carries `publisher_name` / `tracker_name` (paid vs organic).
- [ ] Ad network ↔ analytics link configured (the campaign's installs appear as paid).
- [ ] Campaign / ad group visible somewhere (tracker, GA4 first user campaign).
- [ ] iOS: SKAdNetwork / ATT status if iOS is shipped.

## 3. First-time user experience

- [ ] Loading steps with durations (boot, SDK init, first scene).
- [ ] FTUE steps sent **once per install** (flag persisted in the save), in order:
      first menu, first mode choice, first core-loop start/end, first shop visit, first
      purchase or spend.
- [ ] Tutorial steps, if there is a tutorial.

## 4. Sessions and navigation

- [ ] Sessions (SDK automatic `sessions_starts`, `session_id` on events).
- [ ] Background / foreground or quit (where people leave).
- [ ] Screen opens with stable names (explicit map, not class names) and the previous
      screen (`from_screen`), a per-session step counter for ordering.

## 5. Core loop (match / level / run)

- [ ] Start: mode, level id/index, entry point (menu card, continue button, restart).
- [ ] End: result, **reason**, placement/score, duration, rewards.
- [ ] Fail / lose with reason.
- [ ] Quit — distinguishing quitting a running match from leaving the results screen.
- [ ] Restart with reason.
- [ ] Periodic tick in long matches (elapsed, HP, opponents alive, progress %).
- [ ] Per-match stats: FPS avg/min, slow-frame share, damage split, time to first
      damage / first kill, progress %.
- [ ] Next action after the result screen can be reconstructed.

## 6. Progression

- [ ] Level / career progress, unlocks, difficulty tier.
- [ ] Stars / grades with the thresholds used.

## 7. Economy

- [ ] Every source and sink with a **reason** (source/sink + detail), amount, currency,
      balance before/after — sent from the currency service, not scattered UI code.
- [ ] Balance snapshot at session start and after each core loop.
- [ ] Shop funnel: shop open → item viewed → purchase attempt → success/fail.
- [ ] Dev cheats never reach production analytics.

## 8. Ads (per format: interstitial, rewarded, banner)

- [ ] Requested / loaded / load failed (provider error code, domain, message).
- [ ] Show requested with **placement** and `is_ready`.
- [ ] Shown / opened, show failed, closed; rewarded: reward granted, closed early.
- [ ] Clicked.
- [ ] Per-impression revenue: value, currency, precision, network, ad unit, placement
      (SDK paid callback → `ReportAdRevenue` / client impression event).
- [ ] Suppressions with reason: cooldown, no-ads owned, not ready, replaced.
- [ ] Placement parameter name not reused for another meaning.

## 9. In-app purchases

- [ ] Store initialized / not available.
- [ ] Offer shown (surface, product) → click → success (order id) / fail (game-side
      reason vs store reason) / pending / restore.
- [ ] Revenue reported once (SDK revenue call with verified receipt), not duplicated in
      custom events.
- [ ] Test purchases identifiable (only dev devices, test order ids).

## 10. Performance and technical health

- [ ] FPS / frame time per match or per scene; loading times.
- [ ] Device class: RAM, GPU tier or model (for "slow phones leave" questions).
- [ ] Crashes (SDK crash reporting on) and handled exceptions (reported with dedup,
      not one event per frame).
- [ ] ANR / crash rate from the store (Play vitals) — external.

## 11. Experiments and config

- [ ] A/B group or experiment id on events or as a user property.
- [ ] Remote config version.

## 12. Hygiene

- [ ] Naming convention followed; limits of the strictest provider respected.
- [ ] No events per frame or per physics tick.
- [ ] Enums sent as stable strings.
- [ ] Missing values omitted, not sent as `""` / `0` that look like real values.

---

## Telemetry traps — detect before trusting a number

| Trap | How it showed up | How to detect | Rule |
| --- | --- | --- | --- |
| Guard timer on unscaled time across a fullscreen ad | A timeout guard kept "running" while the ad paused the engine; on resume the first frame carried all elapsed time and the guard fired before the SDK's opened callback → 346 "show_timeout" failures, 342 of them had an ad impression in the same second | join "failure" events to impression events of the same device within ±2 s; count matches | verify "failures" against impressions before believing them; guards must ignore paused time or check the callback state |
| Latency field measured to the wrong moment | a `wait_sec` from request to the moment the event was sent (after returning from the ad) measured ad view duration, not load latency | distribution looks like ad lengths (15–30 s, long tail), correlates with completed views | read where the timer stops; rename or add a field for real load latency |
| Dead constant fields | `AdTypeCount = 0` always, `Network = "Admobe"` always | `catalog`: distinct values = 1 across many rows | report them as dead; never slice by them |
| Suspicious CTR | interstitial CTR 13.7 %, one network 70 % | clicks / impressions per format and network (client events or AdMob) | likely accidental clicks — ad appears under the finger at a navigation tap; AdMob may limit traffic; propose a delay or placement change |
| Failure reasons collapsed | several different outcomes land in one reason (e.g. "load timeout" also used when there was no request record, so early-closed videos land there) | the same reason on `is_ready = true` with long waits | split game-decided reasons from provider-reported ones; send provider error fields only when the provider answered |
| Shared mutable parameter dictionary | a later event carries the state of the previous attempt | same device, consecutive attempts, parameters identical to the previous one | build a fresh dictionary per event |
| FTUE step sent per session | the "first" step repeats on every launch | events per device > 1 for a once-only step | persist the flag in the save |
| Class names as screen names | refactor renames silently split history | a screen name disappears on a version while a new one appears | explicit name map |
| One parameter name, two meanings | `placement` = ad placement in one event, race position in another | catalog: the key's values mix types or domains per event | separate names (`ad_placement`) |
| Per-frame events | volume per device per minute in the hundreds; quota and battery cost | events per session-minute by event name | aggregate into per-match stats or ticks |
| Dev devices in "real" data | the only successful test purchases and doubled "organic" came from team phones | dev flag in the model (analytics-data-model) | exclude before any metric |
