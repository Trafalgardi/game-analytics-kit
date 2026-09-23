# UA economics

Read before writing any number about paid acquisition. Numbers marked *(example)* come
from one real indie game (Android, ad-monetized, Google Ads app campaigns, US-targeted)
and show orders of magnitude, not targets.

## Definitions

| Metric | Definition | Source |
| --- | --- | --- |
| Spend | campaign cost for the window | Google Ads, account clock |
| Network installs | Google Ads "Installs" column | Google Ads |
| Paid players | devices attributed to the network that opened the game (dev excluded) | `v_installs` / model `devices.source_class = 'paid'` |
| Real CPI | spend / paid players | both |
| Cost per retained player | spend / paid players with D1 | both |
| Cohort ARPU | revenue of paid players / paid players, window stated (day 0, to date) | model |
| ROI (ROAS) | cohort revenue / spend | both |
| ROI, upper bound | (paid + all same-days organic revenue) / spend — credits the campaign with every organic player of those days | both |

*(example)* Spend $107.01, Google Ads installs 237, AppMetrica-attributed 159 → real CPI
$0.67; cohort revenue $5.72 → ROI 5.3 %; with same-days organic credited 7.0 %; cost per
D1-retained player $5.35.

## Traps

- **Conversions ≠ installs.** "Conversions" sums every primary action (installs, first
  opens, in-app events). *(example)* 107 conversions at "$0.15" vs 39 players → real $0.40
  per player — exactly the tCPA target that had been set.
- **Console ROAS can be fiction.** Actions with default values ($1 per first open) gave
  value/cost 3.87 while real revenue was 1/11 of the stated value. Check which actions
  carry value and where the value comes from before quoting any console ROAS.
- **The action set changes with the strategy.** On the tROAS day conversions matched
  players 1:1 — periods with different action sets are not comparable per "conversion".
- **Network counts exceed attributed counts** (237 vs 159, 67 %); the rest leaks into
  organic / `unknown` on the same days (attribution shadow).
- **Geo dominates quality.** *(example)* US paid vs US organic: D1 12.6 % vs 11.1 %,
  ARPU $0.038 vs $0.042; organic outside the US: D1 0 %, ARPU 12× lower. Compare paid and
  organic only within the same country tier before blaming a channel.

## tCPA and tROAS math

- **tCPA** bids to a cost per *conversion action*. With installs + first opens as primary
  actions, real CPI per player ends near the target *per player*, not per conversion.
- **tROAS** with target R bids up to *predicted value / R* per install.
  *(example)* $0.13 revenue per US player, R = 50 % → ceiling ≈ $0.26 per install — below
  the $0.40 the same users cost on tCPA. The only way to win auctions is to find users
  predicted to be worth more; with ~5 valuable users in 39 there is no signal to learn
  from. Result *(example)*: $54 spent in one hour (learning phase, budget burst),
  38 installs at $1.43, the same behaviour as before, ROAS 4–5 %.
- **A 50 % ROAS target is a planned 50 % loss** unless revenue keeps arriving after
  day 0. When LTV ≈ install day (70–80 % of ad revenue on day 0, 88 % by D1), it never does.

## Break-even table (put one in every UA report)

Required ARPU = CPI × target ROAS (break-even: ROAS 100 % → ARPU = CPI). Use day-0 ARPU
when LTV ≈ install day.

| CPI | Target ROAS | Required ARPU | Actual ARPU (n) | Gap |
| --- | --- | --- | --- | --- |
| $0.40 | 100 % | $0.40 | $0.036 (n = 159) | ×11 |
| $0.40 | 50 % | $0.20 | $0.036 (n = 159) | ×5.6 |
| $0.67 | 100 % | $0.67 | $0.036 (n = 159) | ×19 |

State the thresholds the product must reach before buying again (e.g. D1, impressions
per install, ARPU) and record the owner's decision in `analytics/notes/findings.md`.

## Buy as a measuring instrument

Until ARPU ≥ CPI, paid traffic is not a revenue channel. It is still useful as an
instrument: a small buy in one country (~$15–20, ~40 fresh players) gives a comparable
cohort to compare builds on the first-session funnel. With n ≈ 40 only large effects are
visible (several-fold, or repeated across buys); keep geo, campaign settings and
day-of-week the same between buys.

## Organic watch

- Show organic installs per day next to paid, split by country tier.
- Paid campaigns lift organic while they run (halo) and part of paid shows up as organic
  or `unknown` (shadow): organic during a campaign is not clean organic.
  *(example)* US organic tripled during the campaign and settled about twice the
  pre-campaign level after it.
- **Organic moves on its own.** *(example)* Installs from Google Play dropped 2.5×
  overnight on a release day in every country — the new build was not even served yet,
  so the cause was store-side (listing, ranking, a review). Check the store listing
  acquisition report and release/listing history before blaming a build.
