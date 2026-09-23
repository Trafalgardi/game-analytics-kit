# Console exports — what exactly to ask for

Console menus move between redesigns. Paths below name the report the way the console
calls it; if the owner cannot find it, ask them to type the report name into the
console's search box or send a screenshot of the menu. For every export ask for:
**date range, filters, time zone of the account, format (CSV)**. Name files
`<console>_<report>_<since>_<until>[_<filter>].csv` in `analytics/imports/raw/`.

## Google Ads (app campaigns) → `--kind google_ads`

1. **Campaign × day** (the base table)
   - Campaigns → Campaigns; date range = the event-data window; Segment → Time → Day.
   - Columns (Modify columns): Cost, Impressions, Clicks, **Installs** (app campaign
     column, not "Conversions"), In-app actions, Conversions, Cost / conv., Conv. value,
     Conv. value / cost, All conv., Bid strategy type, Target CPA / Target ROAS, Budget.
   - Download → CSV.
2. **Conversions by action** — same view, Segment → Conversions → Conversion action.
   Shows how "Conversions" splits into installs, first opens and in-app events.
3. **Conversion setup** — Goals → Conversions → Summary: which actions are **primary**,
   their value setting (same value for each / value from the event / no value), counting.
   A screenshot is fine.
4. **Strategy and budget history** — Change history filtered to the campaign: when the
   bid strategy, target and budget changed (date and time).
5. **Geo** — the Locations report (Insights and reports → When and where ads showed →
   Locations) by day if more than one country is targeted.
6. **Hourly** for launch days and strategy switches: Segment → Time → Hour of day.
7. Account time zone: Admin → Account settings.

Pitfalls: "Conversions" ≠ installs; "Conv. value / cost" is only as real as the values
attached to actions; the conversion set may change when the strategy changes; the
learning phase after a switch can spend a day's budget in an hour.

## AdMob → `--kind admob`

1. **Custom report** (Reports → New report / custom report), filter App = this app,
   **state the country filter** (none / specific).
   - Dimensions: Date, Country, Ad unit (and Format), plus Ad source in the mediation
     report.
   - Metrics: Ad requests, Match rate, Matched requests, Show rate, Impressions,
     Observed eCPM, Estimated earnings, Clicks, CTR.
   - Export → CSV.
2. **User metrics** (when the app is linked to Firebase): ad revenue per user (ARPU),
   ARPDAU, ARPDAV (per daily active viewer).
3. Reporting time zone: Settings (Pacific time unless changed).

Pitfalls: Pacific clock vs the app's clock; earnings are estimates and can be revised;
"show rate" is shown / matched, not shown / offered to the player; very high CTR on
interstitials hints at accidental clicks.

## GA4 / Firebase → `--kind ga4`

1. Reports → Acquisition → User acquisition. Primary dimension **First user primary
   channel group** (older name: "First user default channel group"), then switch to
   **First user campaign**. Metrics: New users, Total revenue, Average revenue per user
   (or engaged sessions / retention if needed).
2. Add a filter or comparison for country and **state it**.
3. Share → Download file → CSV.
4. Retention by cohort: Explore → Cohort exploration (first touch, daily).
5. Property time zone: Admin → Property details.

Use it to cross-check paid users per campaign against AppMetrica's paid devices; it will
not match exactly (different attribution, clocks, consent).

## Google Play Console → `--kind play_console`

1. **Statistics** (app → Statistics): metrics Store listing acquisitions, Store listing
   visitors, conversion rate; breakdown by day and by **country**; Export report → CSV.
2. **Store listing conversion / store analysis** (Grow users → Store performance):
   visitors → acquirers by traffic source (search, explore, third-party referrals).
3. **Bulk monthly reports** (Download reports → Statistics): installs overview, by
   country, by app version; ratings; crashes. These CSVs are UTF-16 encoded — convert a
   copy to UTF-8 if the import fails.
4. **Android vitals** (Monitor and improve → Android vitals): user-perceived ANR rate,
   crash rate, per app version, and the bad-behaviour thresholds.
5. **Ratings and reviews**: rating by day, recent reviews with versions.
6. **What changed and when**: releases and staged rollout percentages (Releases / Publishing
   overview), store listing edits and experiments, price or policy events.
7. Ask which time zone the report shows; if the console does not say, write "not stated".

Pitfalls: a staged rollout means two builds coexist; "acquisitions" are store installs
by new users, not first opens; organic can move on store-side causes on a release day
before the new build is even served.

## App Store Connect → `--kind generic`

1. App Analytics → Metrics / Overview: Impressions, Product Page Views, Conversion Rate,
   Total Downloads (first-time and redownloads), by **Source Type** (App Store Search,
   App Store Browse, Web Referrer, App Referrer) and by territory; export where offered,
   otherwise a screenshot with the range and filters visible.
2. Sales and Trends → units by day if downloads are needed per day.
3. Import with `--kind generic --table asc_<report>`.

Pitfalls: App Analytics counts only users who share data with developers; states its own
time zone; iOS attribution needs SKAdNetwork / ATT context before comparing with Android.

## After any import

- `status` shows the `ext_*` table and row count; sum a key column and compare with the
  console total.
- Record in `analytics/notes/project.md`: file, range, filters, clock, table name.
