# Style guide

The owner reads reports on a phone, forwards them to people who were not in the
conversation, and acts on them. Another agent reads them too, to continue the work. Write
for both: the same skeleton every time, facts apart from readings, every claim traceable to
a number on the page.

## Structure

Every report, in this order (ids and numbers are fixed; the build checks them):

0. **Masthead** — eyebrow (kind · game · build(s) · data window), `h1`, standfirst.
   - **The title is the request**: what was asked, about which game, version and period —
     «MyGame 0.2.0, 08–21.09: полный разбор», «Где теряем новичков в первой сессии»,
     «Окупается ли закупка в США, 17–21.09». Not a slogan and not "Analysis of player
     behaviour". The owner finds reports in the index by what they asked.
   - **The standfirst is the thesis** in one sentence (`meta.json` → `subtitle`, also the
     index line). A figurative thesis («Игра на один матч») belongs here, not in the title.
1. **Summary** (`summary`) — the key-metrics table by build version (`ga.py keymetrics`),
   or 3–4 tiles in a question report; then **short answers**: one row per question the
   owner asked, in their words, the direct answer first ("No.", "Yes, but only in the US."),
   then the number with n and a link to its section.
2. **Product** (`product`) — retention, the drop-off table (`ga.py dropoff`), the core loop
   (actions by their number in the session), leaving after negative events, economy.
3. **Revenue** (`revenue`) — ads by format, placement, network; purchases; UA if any.
4. **Technical** (`tech`) — technical problems and analytics defects, each with the metric
   it biases and the direction.
5. **Countries** (`countries`) — the country split in one place, not scattered.
6. **Hypotheses** (`hypotheses`) — `H1`, `H2`…: claim → numbers it rests on (links) → how to
   test it (metric and threshold) → confidence (high / medium / low).
7. **Recommendations** (`actions`) — ordered by payoff; each → a hypothesis, the expected
   effect (which metric, by how much), how to measure it.
8. **Data I need from you** (`data`, optional) — a checklist: what, where exactly (console
   path), range, filters, format, why.
9. **Method** (`method`) — sources and tables, date windows and time zones, population and
   filters (dev devices, countries, versions), sample rate, definitions, sync time, known gaps.

A **question report** keeps 1, 6, 7 and the method, and of 2–5 only the blocks the question
needs — same order, same numbers (it may read 1, 2, 6, 7). When the version replaces an
earlier one: "What changed since vK" right after the masthead.

Aim: masthead + block 1 fit on two phone screens and are enough on their own; blocks 2–5
are the evidence; 6–7 are what we think and what to do about it.

## Facts and interpretation

- A **fact** is what the data shows: a table, a chart, a sentence with a number and its n
  ("68% close the app on the results screen, n = 212").
- An **interpretation** explains why, or what it means ("the results screen offers no next
  step"). It goes in `<p class="interp">` right after the facts it reads, and is never
  presented as a finding.
- A **hypothesis** (block 6) turns an interpretation into something testable. A
  **recommendation** (block 7) is a change that follows from a hypothesis.
- **Every number used in blocks 1, 6 and 7 appears in a table or chart of blocks 1–5**, and
  the answer or hypothesis links to that section. If a number has no home above, add the
  table (even a two-row one) or drop the number.

## Tone

- Plain, direct, specific. Numbers instead of adjectives ("D1 9.4%", not "low retention").
- Say what is known, what is not, and what would settle it. No hedging filler.
- The owner's decisions recorded in notes are context, not topics to reopen; if the data
  contradicts one, show the evidence neutrally and ask.
- Table and event names belong in the method section or in `code` inline when needed;
  headlines speak the game's language (match, garage, reward), not the database's.
- Corrections of earlier reports are stated openly: what was wrong, why, the new number.

## Numbers

| | Russian (`ru`) | English (`en`) |
| --- | --- | --- |
| Decimal | `0,13` | `0.13` |
| Thousands | `1 234` (narrow no-break space U+202F) | `1,234` |
| Percent | `12,6%` (as `charts.fmt_pct` prints it) | `12.6%` |
| Money | `$0,13`, `$1 234` | `$0.13`, `$1,234` |
| Percentage points | `+5 п. п.` | `+5 pp` |
| Ranges | `17–28.08.2026`, `01–14.09` (en dash) | `Aug 17–28, 2026` |
| Multiples | `в 2,5 раза`, `×11` | `2.5×`, `×11` |

- Units always: $, %, min, s, devices. Currency explicit when not USD.
- Rates always with n: `D1 12,6% (n = 159)`. Small n (< 30) → say "direction only".
- Round to what the sample supports: 12,6% on 159 devices, not 12,58%; money to the
  cent below $10, to the dollar above.
- Medians next to means; distributions for time and money.
- Every day-level number states its clock when sources are mixed.
- In charts, the chart module formats numbers; do not post-process SVG text.

## Device samples

When `status` says the database holds a share of devices (`sample: 5% of devices`):

- rates, medians, per-player means, eCPM and shares stand as they are;
- absolute counts (players, impressions, revenue, installs) are shown as the sample number
  **and** an estimate = sample ÷ rate, marked «≈» and «оценка» (`td.est`), with one line in
  the table note: «выборка 5% устройств, оценка = выборка × 20»;
- never mix an estimate into a rate; say "estimate" in short answers too.

## Caveats

Put a caveat next to the number it qualifies, as a `.note` directly under the table or
chart, or in the tile's qualifier line: incomplete recent days, small n, clock
differences, attribution gaps, telemetry bugs that bias a metric (with the direction).
Never collect them into a disclaimer at the end.

## Charts

- One message per chart; the caption says what to see ("Loss happens before the first
  match ends, not after"), not what is plotted.
- One value axis. No dual axes; two scales → two charts.
- Sort categories by value unless the order is natural (days, funnel steps, time buckets).
- Highlight the point of the chart (`highlight_top`, `.s-bad`/`.s-good`), keep the rest
  neutral; semantic colours: flow/organic, ad/paid, loss/bad, good/revenue.
- Put n in labels or caption; mark incomplete days (band or note).
- ≤ 3 series: label lines/bars directly; more: `legend_html`.
- No pies for more than three parts, no 3D, no stacked bars when the reader must compare
  middle segments.

## Tables

- Numbers right-aligned (`td.n`); totals row `tr.total`; `td.bad` / `td.ok` only where
  the colour carries the point.
- Column headers say unit and base ("D1, % of new devices").
- ≤ 7–8 columns; wider tables scroll inside `.tablebox` — prefer two tables.
- Definitions under the table in `.tnote`.
- Versions compared side by side are columns, older left, newer right, all players last.

## Screenshots

- Only where discussed; crop to the relevant area.
- Tag: `Source · filter · date range` (e.g. `Google Ads · Campaign = US Install · 20–23.08.2026`).
- A `.note` after it: what it shows, what it does not (e.g. "conversions include first
  opens; installs are the next column").
- Two related screenshots side by side in `.shots2`.

## Summary for chat (`report.md` and the chat message)

In the report's order: title (the request), thesis, short answers with numbers and n,
hypotheses one line each with confidence, 1–3 recommendations with their hypothesis, data
still needed, the Artifact link (if published) and the local `report.html` path.
