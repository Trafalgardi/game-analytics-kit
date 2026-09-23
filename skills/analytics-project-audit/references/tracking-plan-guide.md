# Tracking plan guide

Use this when proposing new or fixed events (audit step 9) and when the owner asks for a
full tracking spec to implement.

## Naming and limits

The strictest common provider (Firebase / GA4) sets the limits; design to them even if
only AppMetrica is used today:

- event and parameter names: `snake_case`, Latin letters, start with a letter,
  ≤ 40 characters;
- ≤ 25 parameters per event; string values ≤ 100 characters;
- no reserved prefixes (`firebase_`, `google_`, `ga_`) and no reserved event names
  (`first_open`, `session_start`, `in_app_purchase`, `app_update`, `user_engagement`, ...).

Project conventions that paid off:

- enum values as stable `snake_case` strings (`stunt_race`), never numbers;
- booleans consistently (`"true"`/`"false"` or `1`/`0` — pick one; some teams send both
  under two names for tool compatibility);
- units in the name: `_sec` for seconds, `_ms` for milliseconds; money as integers of
  the in-game currency or as decimal value + ISO currency code for real money;
- a missing value is an absent key, not `""`, `null` or `0`;
- one parameter name = one meaning across all events (`ad_placement` vs `placement`);
- stable names from an explicit map (screen names, modes), never type or class names;
- a small common set on every event (days since install, session count, main balance)
  added by the facade, not by each caller.

## Design rules

- **Every failure has a reason**, split into what the game decided (cooldown, not
  ready, already owned, timeout) and what the provider or store reported (with its raw
  code/message in separate fields, present only when the provider answered).
- **Once-per-install steps** (FTUE) persist their "sent" flag in the save.
- **Revenue once**: real-money revenue through the SDK's revenue call (verified receipt);
  funnel events carry product ids, not prices, to avoid double counting.
- **Economy at the source**: the currency service reports every change with a reason;
  UI code does not.
- **Quit ≠ leave results**: distinguish abandoning a running core loop from closing the
  result screen.
- **No per-frame events**: aggregate into per-match stats and periodic ticks (e.g. every
  30 s); send after heavy moments (scene unload), not during them. Note that adding a
  periodic event changes time-in-game measurement for that build.
- **Timers** that span an ad or a pause use paused-aware time, and stop where the name
  says (load latency stops at "loaded", not at "returned from the ad").
- **Test traffic** is identifiable: dev builds flagged or on a separate key; cheats never
  report as real economy.
- Set a **profile id** if the game has any account or cloud save, so reinstalls and
  multi-device players are one player.

## Plan table

| Priority | Event | Parameters (type, unit) | Where to fire (`file:method`) | Why — the question it answers |
| --- | --- | --- | --- | --- |
| P0 | `<fix: existing_event>` | `reason` (enum) … | `<File.cs:Method>` | "<question>" cannot be answered while … |
| P1 | `<new_event>` | … | … | … |

P0 = broken or misleading data that current reports rely on; P1 = the core loop and
money questions the owner asks now; P2 = nice to have. Keep the plan to what a question
needs; every row names its question.

## Tracking spec outline (when the owner wants it implemented)

Write in the report language; reference code as `file:line`.

1. Transport — providers, the facade class and method, which provider gets which events.
2. Naming conventions and limits (above), the common parameter set and its sources.
3. One section per domain (session and loading, screens, core loop, progression,
   economy, items/shop, IAP, ads, performance): a table *event — parameters — call site*,
   then value dictionaries (every enum value and what it means).
4. How funnels are assembled from these events (each step = one event + condition).
5. Code changes needed (facade API, reporters subscribing to existing signals, no logic
   in per-frame callbacks), and dependency direction (low-level systems expose signals,
   the analytics layer subscribes).
6. Performance requirements (no per-frame events, pooled parameter dictionaries,
   serialization off the hot path).
7. Defects fixed along the way (dead counters, wrong timers, collapsed reasons).
8. Rollout order in small steps, each verifiable.
9. Device verification checklist: for each event, the action that triggers it and what
   the debug log / real-time view must show.
10. Appendix: full parameter reference per event.
