---
name: analytics-import-external
description: "Brings numbers from outside the event stream into the kit: tells the owner exactly which report to export from Google Ads, AdMob, GA4/Firebase, Google Play Console or App Store Connect (console path, columns, date range, filters), loads the CSV with import-csv, reads console screenshots number by number, and reconciles them with event data (conversions vs installs, conversion value, time zones, attribution gaps). Holds UA economics: real CPI, tCPA/tROAS math, break-even ARPU, small buys as a measuring instrument, organic watch. Use for: 'import this CSV', 'here is a screenshot from AdMob', 'what does an install really cost', 'tROAS', «выгрузка из Google Ads», «скрин из AdMob», «сколько стоит установка», «цена установки», «таргет ROAS». Not for AppMetrica syncing (analytics-connect-appmetrica) or the full research write-up (analytics-research)."
---

# External data: consoles, CSV, screenshots

Commands run from the project root (conventions: the `analytics-kit` skill). Read
`analytics/notes/project.md` first: earlier imports, account time zones and conversion
setups may already be recorded.

References — read before asking the owner for anything, and before reading any UA number:
- [references/console-exports.md](references/console-exports.md) — exact reports, columns,
  filters and pitfalls per console.
- [references/ua-economics.md](references/ua-economics.md) — CPI, ROAS, tCPA/tROAS math,
  break-even table, buying as a measuring instrument, organic watch.

## 1. Decide what is needed

Start from the question. Ask only for what changes the answer, per campaign or unit and
per day, for the exact window of the event data you will compare with. Typical needs:

| Question | Export |
| --- | --- |
| Real CPI, payback, bid strategy effect | Google Ads: campaign × day with Installs, conversions by action, value, strategy history |
| Ad revenue, fill, eCPM, CTR | AdMob: ad unit × ad source × country × day |
| Paid vs organic cross-check | GA4: user acquisition by first user campaign / channel group |
| Organic installs, store conversion, vitals, reviews | Play Console statistics, store listing acquisition, Android vitals |
| iOS store funnel | App Store Connect: impressions, product page views, conversion, downloads by source |

## 2. Ask precisely

Write the request in the report language as a checklist the owner can follow without
guessing: console → exact path → columns → segment → **date range** → **filters** →
format (CSV preferred; screenshot acceptable) → where to put the file. Every export and
screenshot must come with its date range and filters stated; one AdMob screenshot once
could not be matched to anything because they were unknown.

Files go to `analytics/imports/raw/` (git-ignored; spend and revenue are account data).
Rename each to `<console>_<report>_<since>_<until>[_<filter>].csv` so the range survives.

## 3. Import CSV

```
py analytics/ga.py import-csv analytics/imports/raw/google_ads_campaign_day_2026-08-20_2026-08-23.csv --kind google_ads
py analytics/ga.py import-csv analytics/imports/raw/admob_unit_country_2026-08-20_2026-08-23.csv --kind admob --table admob_units
py analytics/ga.py import-csv analytics/imports/raw/asc_sources_2026-09.csv --kind generic --table asc_sources
```

Kinds: `google_ads`, `admob`, `ga4`, `play_console`, `generic` (App Store Connect and
anything else). `--table NAME` names the `ext_*` table; `--replace` reloads it. Then check:
`status` (new table, rows), `sql "SELECT * FROM ext_<table> LIMIT 5"`, and that the sum
of a key column equals the console total. If parsing fails: title lines above the header,
"Total" rows at the bottom, locale number formats (`1 234,5`, `12.5%`, currency symbols),
or UTF-16 encoding (Play Console bulk reports). Keep the original, save a cleaned copy
with a `_clean` suffix, never edit numbers.

## 4. Read screenshots

1. Write down every number you use with its row and column label, the filter and the date
   range visible on the screen, into `work/screens.md` of the current report (or the notes).
2. If the range or filters are not visible, ask the owner — do not infer them from the
   numbers.
3. Note duplicates (same report sent twice, overlapping ranges) and totals vs rows.
4. Quote exact values as shown (rounding, currency, time zone); mark values you read from
   a chart axis as approximate.
5. A screenshot the report relies on is copied into the report's `assets/` and embedded
   with its tag (source · filter · date range) — see the `analytics-report` skill.

## 5. Reconcile with event data

- **Conversions are not installs.** Google Ads "Conversions" sums every primary
  conversion action (installs, first opens, in-app events). Real case: 107 conversions at
  "$0.15" vs 39 attributed players → $0.40 per player. Real CPI = spend / paid devices
  that opened the game (AppMetrica `v_installs` paid class; cross-check GA4 first user
  campaign).
- **Check conversion value before any console ROAS.** Actions with default values
  ($1 per first open) showed value/cost 3.87 while real revenue was 1/11 of the stated
  value. Ask which actions are primary and where their value comes from.
- **The conversion set can change with the strategy** — on the tROAS day conversions
  matched players 1:1. Compare periods only with the same action set.
- **Network counts exceed ours**: Google Ads 237 installs, AppMetrica attributed 159
  (67 %). Part of the gap appears as organic or `unknown` on the same days; in paid
  periods `unknown` is mostly paid-adjacent.
- **Clocks differ**: Google Ads = account time zone, AdMob = Pacific by default, GA4 =
  property time zone, AppMetrica = app time zone. Compare over whole multi-day windows,
  re-bucket AppMetrica by `event_timestamp` into the other clock when a day matters, and
  say which clock every number uses.
- Revenue: AdMob earnings vs `ad_revenue_events` for the same range and countries should
  be close; a large gap means missing paid callbacks or a filter mismatch.

## 6. Record

- `analytics/notes/project.md`: account time zones, conversion actions and their value
  sources, strategy and target history as known, which imports exist (file, range,
  filters, table).
- The report's method section: every external number with its console, range, filter
  and clock.
