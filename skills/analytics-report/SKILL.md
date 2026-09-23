---
name: analytics-report
description: "Writes, builds and publishes the kit's versioned, self-contained HTML reports in one fixed skeleton: 1 summary (key-metrics table by build version + short answers), 2 product, 3 revenue, 4 technical, 5 countries, 6 hypotheses (H1, H2… each resting on linked numbers), 7 recommendations (each linked to a hypothesis, with expected effect and measure), then data requests and method. Creates a full review or a question report with 'report new --kind', titles it with the request, embeds the engine's standard tables (keymetrics, dropoff), draws SVG charts, embeds owner screenshots, writes report.md, builds (the build checks the skeleton and every link), and publishes it (an Artifact where the environment supports it; the local report.html always). Use whenever findings must become a document: 'write a report', 'update the report', 'publish the report', «сделай отчёт», «оформи отчёт», «обнови отчёт», «новая версия отчёта». Not for deciding what the numbers are (analytics-research) or auditing tracking (analytics-project-audit) — those skills end by calling this one."
---

# Write and publish a report

Commands run from the project root (conventions: the `analytics-kit` skill). Write in
`analytics/analytics.toml` → `[project].report_language`. References — read both before
writing the first section:
- [references/style-guide.md](references/style-guide.md) — the skeleton, the title rule,
  facts vs interpretation, tone, number formatting (ru/en), sample estimates, charts, tables.
- [references/components.md](references/components.md) — HTML for every block and component.

## 1. The skeleton (every report, both kinds)

The owner asked for one transparent structure, the same in every report, so a reader and
an agent find each thing in the same place. Block numbers and ids are fixed:

| # | id | What goes there |
| --- | --- | --- |
| 1 | `summary` | key-metrics table (rows: D1/D3/D7, time per player, sessions, session length, interstitials and rewarded per player, ARPU, revenue, players; **columns: build versions**) — or 3–4 tiles in a question report — then **short answers**, one per question asked |
| 2 | `product` | everything about the game except money: retention, the **drop-off table** (loading/FTUE steps, then every 30 s of the first 10 minutes), core loop, leaving after negative events, economy |
| 3 | `revenue` | ads by format, placement, network (impressions per player, eCPM), purchases |
| 4 | `tech` | technical problems and analytics defects: duplicates, empty or constant fields, broken parameters, sources that disagree |
| 5 | `countries` | the country split, in one place |
| 6 | `hypotheses` | `H1`, `H2`… claim → the numbers it rests on (links to blocks 2–5) → how to test it (metric and threshold) → confidence |
| 7 | `actions` | recommendations, each → a hypothesis, with the expected effect and how to measure it |
| — | `data`, `method` | data I need from you (if any), method (always) |

- **Kinds.** `full` = the full review of a game over a period: all blocks. `question` =
  one question: blocks 1, 6, 7 and method always; of 2–5 only those it needs, in this order,
  numbers kept (a question report may read 1, 3, 6, 7).
- **Title = the request**, in the form «<Game> <version>, <period>: <what was asked>» — «MyGame
  0.2.0, 08–21.09: полный разбор», «MyGame: где теряем новичков в первой сессии». The game's
  name comes first, also when it is in the eyebrow. The thesis goes into
  the standfirst (`meta.json` → `subtitle`). Slug from the request too: `full-review-2026-09-08-21`,
  `first-session-loss`; a new period is a new slug, a correction is a new version.
- **Facts vs interpretation.** Tables, charts and plain sentences state facts; a reading of
  them goes in `<p class="interp">`. Every number used in blocks 1, 6 and 7 appears in a
  table or chart of blocks 1–5, and hypotheses link to it.

## 2. Create the version

```
py analytics/ga.py report new <slug> --kind full --title "<the request>"
py analytics/ga.py report new <slug> --kind question --title "<the request>"
py analytics/ga.py report new <slug> --title "<the request>" --from v001    # a change to v001, kind kept
```

It prints `analytics/reports/<slug>/vNNN/` with `report.src.html` (the kind's scaffold, block
names already in the report language — keep the skeleton, fill or delete every TODO),
`meta.json`, `assets/`, `work/`. In `meta.json` fill `subtitle` (the thesis: standfirst and
index line), `question`, `data_window.since/until`, `sources_used` — the build fails on an
empty field a `{{meta:...}}` needs.

## 3. The standard tables (engine, not hand-made)

```
V=analytics/reports/<slug>/vNNN/assets
py analytics/ga.py keymetrics --since D --until D --players P --format html --out $V/keymetrics.html
py analytics/ga.py dropoff    --since D --until D --players P --steps <steps view> --format html --out $V/dropoff.html --svg $V/dropoff.svg
py analytics/ga.py ordinals   --since D --until D --players P --events <core actions> --format html --out $V/ordinals.html
py analytics/ga.py leaving    --since D --until D --players P --events <negative events>,<a neutral one> --pause <...> --format html --out $V/leaving.html
```

Embed them with `{{html:assets/<name>.html}}` (+ `{{svg:assets/dropoff.svg}}`): key metrics in
block 1, drop-off in 2.2, ordinals in the core-loop section, leaving in the negative-events
section. Run them without `--format html` first to read the numbers. **One population for the
whole report**: the same `--since/--until/--players` in every table and in your own queries,
and the lede of block 1 says which (new players by the project's rule, not "first seen").
The steps view and the players filter come from the project model (`analytics-data-model`,
modeling guide §11–15). They are sample-aware: estimates are marked ≈ and explained.

## 4. Write `report.src.html`

Compact reference (full snippets in components.md):

```html
<section class="block" id="product">
<h2><span class="bn">2</span>Продуктовые метрики</h2>
<p class="lede">The claim of the block.</p>
<h3 id="product-dropoff">2.2 Отвалы по шагам и по времени</h3>
{{html:assets/dropoff.html}}
<figure><div class="figbox">{{svg:assets/dropoff.svg}}</div><figcaption>What to see.</figcaption></figure>
<p class="interp"><b>Интерпретация.</b> The reading, marked as such.</p>
</section>

<article class="hyp" id="h1">
  <p class="hid">H1 <span class="conf high">уверенность высокая</span></p>
  <h4>The claim</h4>
  <p class="basis"><b>Опора:</b> 21,2% leave at the first purchase (<a href="#product-dropoff">2.2</a>).</p>
  <p class="test"><b>Как проверить:</b> the loss at that step below 10% at n ≥ 150.</p>
</article>

<div class="act"><div><h4>Action</h4><p>What exactly.</p>
  <p class="eff"><b>Ожидаемый эффект:</b> which metric moves, by how much.</p>
  <p class="measure"><b>Как мерить:</b> metric, cohort, when.</p>
  <p class="why">→ <a href="#h1">H1</a></p></div></div>
```

Give every piece of evidence you cite an id (`h3 id="product-core"`, `figure id=...`) and
link to it. Placeholders: `{{svg:assets/x.svg}}`, `{{img:assets/x.png}}` (png, jpg, webp,
gif), `{{html:assets/x.html}}`, `{{meta:field}}` (dotted paths, plus `version_label`,
`built_date` and `window` — the data window as people write it, `08–21.09.2026`). HTML
comments are dropped.

## 5. Charts

Write `work/charts.py`, run it from the project root, save SVGs into `assets/`:

```python
import sqlite3, sys
sys.path.insert(0, 'analytics/kit')
from gak.report import charts

V, LANG = 'analytics/reports/first-session-loss/v001', 'ru'   # LANG = report_language
db = sqlite3.connect('file:analytics/data/analytics.db?mode=ro', uri=True)
rows = db.execute("SELECT first_date, COUNT(*) FROM v_players GROUP BY 1 ORDER BY 1").fetchall()
svg = charts.bar([r[0] for r in rows], [r[1] for r in rows], lang=LANG, title='New players per day')
with open(f'{V}/assets/new_players.svg', 'w', encoding='utf-8') as f:
    f.write(svg)
```

Functions: `bar`, `hbars` (long labels), `grouped_bars`, `stacked_bars`, `line` (series
= `[(label, css_class, values), ...]`), `ranked_bars` (concentration: `highlight_top=N`,
`mean_line`, `median_line`), `legend_html([(label, css_class), ...])` (paste its output
into the `.figbox` above the SVG), `bands=[charts.annotate_band(x_from, x_to, label)]`
(mark incomplete days). Common keywords: `lang`, `unit` (`"$"`, `"%"`, any suffix),
`decimals`, `highlight`, `title`. Always pass `lang` — it defaults to `ru`. Series classes:
`s1..s6` in order, `s-old`, `s-unk`, `s-good`, `s-bad`. Never post-process an SVG with string
replacement (it corrupts coordinates). `help(charts.<name>)` shows the rest.

## 6. Screenshots

Copy the owner's images from `analytics/imports/` into `assets/` (crop to the relevant
part if you can), embed with `{{img:assets/<file>}}` inside `.shot` with a tag
`source · filter · date range`, and a line on what it shows and what it does not.
No range or filter known → ask before using it.

## 7. `report.md`

A short summary for chat and messengers in the report language, in the report's order:
title (the request), thesis, short answers with numbers and n, the hypotheses in one line
each with confidence, the top 1–3 recommendations with their hypothesis, data still needed,
link/path. The scaffolded `report.md` has this shape.

## 8. Check, then build

A successful build is final, so check the source first: no TODO left; every number in
blocks 1, 6, 7 appears in a table or chart above and matches `work/claims.md`; units and n
everywhere; every chart has a caption; meta.json filled; assets exist.

```
py analytics/ga.py report build <slug>          # latest version; --version N for another
```

The build refuses (and writes nothing) on an unresolved placeholder, a missing asset, an
empty meta field, and — for `full` / `question` — on a broken skeleton: a missing or
misordered block, a duplicate id, a link to no id, a hypothesis without a confidence mark or
without a link to its numbers, a recommendation without a link to a hypothesis, `.eff` or
`.measure`. It lists every problem with its line; fix them all and rerun. After a
successful build check:
- `report.html` and `artifact.html` exist; `artifact.html` starts with `<title>`;
- size: a few hundred KB is normal; several MB means oversized screenshots — note it and
  crop or shrink them in the next version;
- no `{{` left, no `<script src`, no external images: only Google Fonts load remotely;
- if you can open a browser, look at it once at ~400 px width and in dark mode.

## 9. Publish

- If your environment can publish an Artifact, publish `artifact.html` and give the owner
  the link. For a later version, update that same Artifact so the owner's link keeps
  working, and say which version it now shows.
- Always give the local path `analytics/reports/<slug>/vNNN/report.html` (it opens from
  disk and can be sent as a file) and mention `analytics/reports/index.html`
  (`py analytics/ga.py report index` if it looks stale).

## Versioning

- Built = immutable: the builder refuses to build a version twice; never hand-edit
  `report.html`, `artifact.html` or `meta.json` of a built version.
- Any change — a typo found after the build, new data, a correction — goes into
  `report new <slug> --title "<the request>" --from vK`, which copies source, summary and
  assets and carries over kind and meta fields. The new body opens with "What changed since
  vK" (what was wrong or new, which numbers moved).
- A report made before kinds existed has no `kind` and no skeleton check; its next version
  keeps that unless you pass `--kind` (then rewrite the body into the skeleton).

## Writing rules

- Title = the request; the standfirst = the thesis in one sentence.
- Short answers: one row per question asked, direct answer first, the number with n and a
  link to its section.
- Each section: lede sentence → table or chart → interpretation in `.interp`. Every chart
  has a caption that says what to see.
- Hypotheses: numbered, each with its evidence link, a test with a threshold, a confidence.
- Recommendations: ordered by payoff, each → a hypothesis, expected effect, how to measure.
- Owner screenshots where they are discussed, with tag and note.
- Caveats as notes next to the number they qualify, not in a disclaimer at the end.
- "Data I need from you": a checklist with exact console paths, ranges and filters.
- Method: sources, date windows, time zones, filters (dev devices), sample rate, definitions.
- Sampled database: absolute numbers carry "≈" and "оценка" (sample ÷ rate); rates as they are.
- Russian: decimal comma, thin-space thousands (`0,13`, `1 234`); units always ($, %, min).
