"""Texts of the example reports in both languages (made-up numbers). Used by make_sample.py."""

# --------------------------------------------------------------------------- English

BODY_EN = """<!-- Example of a full review: every block of the fixed skeleton and every component. Numbers are made up. -->
<div class="wrap">

<header class="masthead">
  <p class="eyebrow">Full review · Sample · 1.0.8 and 1.1.0 · {{meta:window}}</p>
  <h1>{{meta:title}}</h1>
  <p class="standfirst">{{meta:subtitle}}</p>
</header>

<nav class="toc">
  <a href="#summary"><b>1</b>Summary</a>
  <a href="#product"><b>2</b>Product metrics</a>
  <a href="#revenue"><b>3</b>Revenue metrics</a>
  <a href="#tech"><b>4</b>Technical data</a>
  <a href="#countries"><b>5</b>Countries</a>
  <a href="#hypotheses"><b>6</b>Hypotheses</a>
  <a href="#actions"><b>7</b>Recommendations</a>
</nav>

<section class="block" id="summary">
<h2><span class="bn">1</span>Summary</h2>
<p class="lede">New players of Sep 1–20 by the build of their first launch. Every number is made up: the example shows what each block looks like.</p>

<h3 id="summary-metrics">Key metrics by version</h3>
{{html:assets/keymetrics.html}}

<h3 id="summary-answers">Short answers</h3>
<div class="answers">
  <div class="ans"><div class="q">What did 1.1.0 change</div>
    <div><p><b>More players finish the first match, no more reach the second.</b> 74% vs 62%, second match 45% vs 52% (<a href="#product-core">2.3</a>).</p></div></div>
  <div class="ans"><div class="q">Where do we lose new players</div>
    <div><p><b>At the first purchase in the tutorial and in the first 30 seconds of play.</b> 21.2% and 11.3% leave (<a href="#product-dropoff">2.2</a>).</p>
    <p>A second paragraph inside an answer works too.</p></div></div>
  <div class="ans"><div class="q">Does paid UA pay back</div>
    <div><p><b>No.</b> A player costs $0.40 and brings $0.13 (<a href="#revenue-ua">3.3</a>).</p></div></div>
</div>
</section>

<section class="block" id="product">
<h2><span class="bn">2</span>Product metrics</h2>
<p class="lede">Everything about the game except money: installs and retention, drop-off, the first matches, what players do before they leave.</p>

<h3 id="product-retention">2.1 New players and D1 by day</h3>
<figure id="fig-daily">
  <div class="figbox">
    <div class="legend"><span><i class="sw s1"></i>Organic</span><span><i class="sw s2"></i>Paid</span><span><i class="sw s-unk"></i>Unattributed</span></div>
    {{svg:assets/daily.svg}}
  </div>
  <figcaption>From Sep 15 organic drops about 2.5×, paid starts on Sep 17. Hover a bar for the split.</figcaption>
</figure>
<figure id="fig-retention">
  <div class="figbox">
    <div class="legend"><span><i class="sw lk s-old"></i>Build 1.0.8</span><span><i class="sw lk s1"></i>Build 1.1.0</span></div>
    {{svg:assets/retention.svg}}
  </div>
  <figcaption>line: two series with a gap (None), markers, the value at the end of the line, a band and a vertical mark.</figcaption>
</figure>
<p class="note"><b>Preliminary.</b> The last seven days are still arriving: D1 for Sep 19–20 can grow. A .note sits next to the number it qualifies.</p>

<h3 id="product-dropoff">2.2 Drop-off by steps and by time</h3>
{{html:assets/dropoff.html}}
<figure>
  <div class="figbox">{{svg:assets/dropoff.svg}}</div>
  <figcaption>Most players leave in the first 30 seconds of active time; after that the loss is steady, 3–6% per interval.</figcaption>
</figure>
<p class="interp"><b>Interpretation.</b> The first purchase in the tutorial needs money a new player does not have yet: 21.2% never get past it. This is a reading of the numbers, not a fact — H1 tests it.</p>

<h3 id="product-core">2.3 The first matches</h3>
{{html:assets/ordinals.html}}
<figure>
  <div class="figbox">
    <div class="legend"><span><i class="sw s-old"></i>Build 1.0.8 (neutral .s-old)</span><span><i class="sw s1"></i>Build 1.1.0</span></div>
    {{svg:assets/matches.svg}}
  </div>
  <figcaption>grouped_bars: values above the bars when they fit. The distributions nearly match.</figcaption>
</figure>
<div class="tablebox">
<table>
  <thead><tr><th>New players</th><th class="n">1.0.8</th><th class="n">1.1.0</th><th class="n">Difference</th></tr></thead>
  <tbody>
    <tr><td>Players</td><td class="n">118</td><td class="n">94</td><td class="n">−24</td></tr>
    <tr><td>Finished the first match</td><td class="n">62%</td><td class="n ok">74%</td><td class="n ok">+12 pp</td></tr>
    <tr><td>Started a second match</td><td class="n">52%</td><td class="n bad">45%</td><td class="n bad">−7 pp</td></tr>
    <tr><td>Playtime, median</td><td class="n">5.3 min</td><td class="n">5.4 min</td><td class="n">+0.1</td></tr>
    <tr class="total"><td>Sessions in total</td><td class="n">342</td><td class="n">291</td><td class="n">−51</td></tr>
  </tbody>
</table>
</div>
<p class="tnote">.tnote under a table: cohorts, window, filters. td.n numbers, td.ok / td.bad a verdict, tr.total a total.</p>
<p class="interp"><b>Interpretation.</b> 1.1.0 moved the loss from the first match to the step to the second one. 7 pp on 94 players is a direction, not a proven effect.</p>

<h3 id="product-negative">2.4 Leaving after negative events</h3>
{{html:assets/leaving.html}}
<p class="interp"><b>Interpretation.</b> After a theft 46.7% background the game — twice as often as after a neutral purchase (22.8%).</p>
<figure>
  <div class="figbox">
    {{svg:assets/reasons.svg}}
  </div>
  <figcaption>Every fourth player who left backgrounded the game within 20 seconds of a theft.</figcaption>
</figure>
</section>

<section class="block" id="revenue">
<h2><span class="bn">3</span>Revenue metrics</h2>
<p class="lede">Ads by format, placement and network; revenue concentration; paid acquisition.</p>

<h3 id="revenue-ads">3.1 Ads by placement</h3>
<div class="tablebox">
<table>
  <thead><tr><th>Placement</th><th class="n">Impressions in the sample</th><th class="n">Impressions, estimate</th><th class="n">Per player</th><th class="n">eCPM, $</th></tr></thead>
  <tbody>
    <tr><td>Interstitial after a match</td><td class="n">612</td><td class="n est">≈ 6,120</td><td class="n">2.9</td><td class="n">3.10</td></tr>
    <tr><td>Rewarded: double the reward</td><td class="n">118</td><td class="n est">≈ 1,180</td><td class="n">0.6</td><td class="n ok">6.40</td></tr>
    <tr><td>Rewarded: second chance</td><td class="n">31</td><td class="n est">≈ 310</td><td class="n">0.1</td><td class="n">5.90</td></tr>
    <tr class="total"><td>Total</td><td class="n">761</td><td class="n est">≈ 7,610</td><td class="n">3.6</td><td class="n">3.72</td></tr>
  </tbody>
</table>
</div>
<p class="tnote">≈ an estimate from a 10% device sample (× 10), italic .est. Shares and per-player values stand as they are.</p>
<figure>
  <div class="figbox">
    LEGEND_NETWORKS
    {{svg:assets/networks.svg}}
  </div>
  <figcaption>Six categorical colours in order. There is never a seventh series: the rest folds into "other".</figcaption>
</figure>

<h3 id="revenue-concentration">3.2 Revenue sits with a few players</h3>
<figure>
  <div class="figbox">
    <div class="legend"><span><i class="sw s2"></i>Top five</span><span><i class="sw s1"></i>Everyone else</span></div>
    {{svg:assets/revenue.svg}}
  </div>
  <figcaption>Five players pull the mean up; the median is several times lower.</figcaption>
</figure>

<h3 id="revenue-ua">3.3 Paid acquisition</h3>
<div class="calc">Break-even revenue per player (example):
  cost $0.40, ROAS 100%  →  need $0.40 per player   (now $0.13, ×3.1)
  cost $0.40, ROAS 50%   →  need $0.20              (×1.5)</div>
<figure>
  <div class="figbox">
    <div class="legend"><span><i class="sw s-good"></i>In profit (.s-good)</span><span><i class="sw s-bad"></i>At a loss (.s-bad)</span></div>
    {{svg:assets/margin.svg}}
  </div>
  <figcaption>bar with negative values: a bar grows down from zero, only the data end is rounded.</figcaption>
</figure>
<div class="shot"><p class="tag">Console · all countries · Sep 17–20</p>
  <div class="frame"><img alt="A made-up console screenshot: five blue bars on a white card" src="{{img:assets/console.png}}"></div>
  <p class="tnote">What the screenshot shows and what it does not.</p></div>
<div class="shots2">
  <div class="shot"><p class="tag">Console · US · Sep 17–20</p><div class="frame"><img alt="A made-up screenshot: orange bars" src="{{img:assets/console_a.png}}"></div></div>
  <div class="shot"><p class="tag">Console · US · Sep 21</p><div class="frame"><img alt="A made-up screenshot: green bars" src="{{img:assets/console_b.png}}"></div></div>
</div>
</section>

<section class="block" id="tech">
<h2><span class="bn">4</span>Technical data</h2>
<p class="lede">Technical problems and analytics defects. .cards: .hot loss, .adc ads, .okc good.</p>
<div class="cards">
  <div class="card hot" id="tech-duplicates"><div class="cnt">38%<em>of events</em></div><h4>Duplicated income</h4><p>One payout arrives as two events: economy totals are doubled.</p></div>
  <div class="card adc" id="tech-timeouts"><div class="cnt">346<em>errors</em></div><h4>False ad timeouts</h4><p>342 of them are real impressions in the same second.</p></div>
  <div class="card okc"><div class="cnt">60<em>FPS</em></div><h4>Performance is fine</h4><p>An .okc card.</p></div>
  <div class="card"><h4>Telemetry details</h4><p>A card without a number or a modifier; <code>AdImpression</code> as code.</p></div>
</div>
</section>

<section class="block" id="countries">
<h2><span class="bn">5</span>Countries</h2>
<p class="lede">The country split in one place.</p>
<div class="tablebox">
<table>
  <thead><tr><th>Country</th><th class="n">Players</th><th class="n">D1</th><th class="n">Playtime, median</th><th class="n">ARPU, $</th><th class="n">Share of revenue</th></tr></thead>
  <tbody>
    <tr><td>US</td><td class="n">81</td><td class="n ok">38.3%</td><td class="n">6.1 min</td><td class="n ok">0.031</td><td class="n">71%</td></tr>
    <tr><td>Brazil</td><td class="n">64</td><td class="n">31.1%</td><td class="n">5.0 min</td><td class="n">0.004</td><td class="n">9%</td></tr>
    <tr><td>India</td><td class="n">67</td><td class="n bad">27.4%</td><td class="n">4.6 min</td><td class="n bad">0.002</td><td class="n">5%</td></tr>
    <tr class="total"><td>All</td><td class="n">212</td><td class="n">32.8%</td><td class="n">5.3 min</td><td class="n">0.013</td><td class="n">100%</td></tr>
  </tbody>
</table>
</div>
</section>

<section class="block" id="hypotheses">
<h2><span class="bn">6</span>Hypotheses</h2>
<p class="lede">What we think is going on. Each hypothesis rests on numbers from blocks 2–5 and says how to test it.</p>
<div class="hyps">
  <article class="hyp" id="h1">
    <p class="hid">H1 <span class="conf high">confidence high</span></p>
    <h4>The first purchase in the tutorial is too expensive</h4>
    <p class="basis"><b>Rests on:</b> 21.2% of those who reach the "first purchase" step leave there (<a href="#product-dropoff">2.2</a>).</p>
    <p class="test"><b>How to test:</b> give starting money for the purchase; confirmed if the loss at that step falls below 10% at n ≥ 150.</p>
  </article>
  <article class="hyp" id="h2">
    <p class="hid">H2 <span class="conf mid">confidence medium</span></p>
    <h4>After the first match the player is not offered a next step</h4>
    <p class="basis"><b>Rests on:</b> 45% start a second match vs 52% (<a href="#product-core">2.3</a>); players leave right after the results screen (<a href="#product-negative">2.4</a>).</p>
    <p class="test"><b>How to test:</b> the share starting a second match ≥ 60% in a new build, same countries.</p>
  </article>
  <article class="hyp" id="h3">
    <p class="hid">H3 <span class="conf low">confidence low</span></p>
    <h4>Paid UA in the US can pay back only through rewarded ads</h4>
    <p class="basis"><b>Rests on:</b> rewarded eCPM 6.40 vs 3.10 for interstitials (<a href="#revenue-ads">3.1</a>), a player costs $0.40 (<a href="#revenue-ua">3.3</a>).</p>
    <p class="test"><b>How to test:</b> 7-day ARPU ≥ $0.40 for a paid cohort after rewarded placements are added.</p>
  </article>
</div>
</section>

<section class="block" id="actions">
<h2><span class="bn">7</span>Recommendations</h2>
<p class="lede">Ordered by payoff. .acts numbers them itself.</p>
<div class="acts">
  <div class="act"><div><h4>Give starting money for the first purchase</h4>
    <p>Grant the price of the first purchase when the tutorial starts.</p>
    <p class="eff"><b>Expected effect:</b> the loss at the "first purchase" step from 21% to ~10%, +20 of 212 players reach the game.</p>
    <p class="measure"><b>How to measure:</b> ga.py dropoff on the new build a week later, n ≥ 150.</p>
    <p class="why">→ <a href="#h1">H1</a></p></div></div>
  <div class="act"><div><h4>A "Next match" button on the results screen</h4>
    <p>The main button starts the next match; the garage comes second.</p>
    <p class="eff"><b>Expected effect:</b> second-match starts from 45% to 60%.</p>
    <p class="measure"><b>How to measure:</b> the share starting a second match among those who finished the first, new players.</p>
    <p class="why">→ <a href="#h2">H2</a></p></div></div>
  <div class="act"><div><h4>Buy traffic to measure, not to earn</h4>
    <p>A small budget per build, one country.</p>
    <p class="eff"><b>Expected effect:</b> 40 new players per build for $16 — builds compared without organic noise.</p>
    <p class="measure"><b>How to measure:</b> the key metrics of block 1 by version.</p>
    <p class="why">→ <a href="#h3">H3</a></p></div></div>
</div>
</section>

<section class="block" id="data">
<h2>Data I need</h2>
<ul class="tight">
  <li><b>Console → Reports → By day:</b> spend and installs for the report window.</li>
  <li><b>Store → Listing statistics:</b> visitors and listing conversion by day.</li>
</ul>
</section>

<section class="method" id="method">
  <h2>Method</h2>
  <ul class="tight">
    <li>Report {{meta:version_label}} "{{meta:title}}", built {{meta:built_date}}. Data window {{meta:window}}.</li>
    <li>Sources: {{meta:sources_used}}. Question: {{meta:question}}</li>
    <li>Tables of blocks 1 and 2 — <code>ga.py keymetrics</code>, <code>dropoff</code>, <code>ordinals</code>, <code>leaving --format html</code>; charts — <code>gak.report.charts</code>; build — <code>py analytics/ga.py report build sample</code>.</li>
  </ul>
</section>

</div>
"""

CHANGES_V2_EN = """</header>

<p class="note"><b>What changed since v001.</b> The data window extends to Sep 21, the ROAS line in 3.3 was recounted. Everything else as before.</p>
"""

QUESTION_BODY_EN = """<!-- Example of a question report: blocks 1, 3, 6, 7 and the method. Numbers are made up. -->
<div class="wrap">

<header class="masthead">
  <p class="eyebrow">Question · Sample · paid UA in the US · {{meta:window}}</p>
  <h1>{{meta:title}}</h1>
  <p class="standfirst">{{meta:subtitle}}</p>
</header>

<section class="block" id="summary">
<h2><span class="bn">1</span>Summary</h2>
<div class="tiles">
  <div class="tile ad"><p class="k">Cost per player</p><div class="v">$0.40</div><p class="n">spend / 39 players · .tile.ad</p></div>
  <div class="tile"><p class="k">Revenue per player</p><div class="v">$0.13</div><p class="n">n = 39 · .tile — neutral</p></div>
  <div class="tile warn"><p class="k">ROAS</p><div class="v">33% → 5%</div><p class="n">CPI → tROAS · .tile.warn</p></div>
  <div class="tile good"><p class="k">Revenue on install day</p><div class="v">80%</div><p class="n">n = 39 · .tile.good</p></div>
</div>
<h3 id="summary-answers">Short answers</h3>
<div class="answers">
  <div class="ans"><div class="q">Does paid UA in the US pay back</div>
    <div><p><b>No.</b> A player costs $0.40 and brings $0.13, and 80% of the revenue comes on the install day (<a href="#revenue-payback">3.1</a>).</p></div></div>
</div>
</section>

<section class="block" id="revenue">
<h2><span class="bn">3</span>Revenue metrics</h2>
<p class="lede">A question report keeps only the blocks it needs, with the same numbers and in the same order.</p>
<h3 id="revenue-payback">3.1 Payback</h3>
<div class="calc">$15.60 spend / 39 players = $0.40 per player
revenue $5.07 / 39 = $0.13 per player → ROAS 33%</div>
<figure>
  <div class="figbox">
    <div class="legend"><span><i class="sw s2"></i>Top five</span><span><i class="sw s1"></i>Everyone else</span></div>
    {{svg:assets/revenue.svg}}
  </div>
  <figcaption>Revenue rests on five players of 39; the median is $0.04.</figcaption>
</figure>
<p class="interp"><b>Interpretation.</b> With no valuable players in the sample, a ROAS bid has nobody to buy.</p>
</section>

<section class="block" id="hypotheses">
<h2><span class="bn">6</span>Hypotheses</h2>
<div class="hyps">
  <article class="hyp" id="h1">
    <p class="hid">H1 <span class="conf high">confidence high</span></p>
    <h4>Revenue per player is a third of its cost under any bidding strategy</h4>
    <p class="basis"><b>Rests on:</b> $0.13 vs $0.40 (<a href="#revenue-payback">3.1</a>).</p>
    <p class="test"><b>How to test:</b> 7-day ARPU of the next paid cohort ≥ $0.40.</p>
  </article>
</div>
</section>

<section class="block" id="actions">
<h2><span class="bn">7</span>Recommendations</h2>
<div class="acts">
  <div class="act"><div><h4>Stop buying traffic for revenue</h4>
    <p>Keep a small budget only to compare builds.</p>
    <p class="eff"><b>Expected effect:</b> $50 less loss a day.</p>
    <p class="measure"><b>How to measure:</b> the daily UA margin in the next report.</p>
    <p class="why">→ <a href="#h1">H1</a></p></div></div>
</div>
</section>

<section class="method" id="method">
  <h2>Method</h2>
  <ul class="tight">
    <li>Report {{meta:version_label}}, built {{meta:built_date}}. Data window {{meta:window}}. Every number is made up.</li>
  </ul>
</section>

</div>
"""

MD_EN = """# Sample 1.0.8 and 1.1.0, Sep 1–20: full review

{until} · sample {label} · every number is made up

New players leave at the first purchase in the tutorial, and paid UA does not pay back at any bid.

**Short answers**
- 1.1.0: more finish the first match (74% vs 62%), fewer start a second (45% vs 52%), n = 94 / 118.
- The biggest losses: the first purchase in the tutorial (21.2%) and the first 30 seconds of play (11.3%), n = 212.
- Paid UA: a player costs $0.40 and brings $0.13.

**Hypotheses**
- H1 — the first purchase is too expensive (high).
- H2 — no next step after the first match (medium).

**What to do**
1. Starting money for the first purchase (→ H1): the loss at the step from 21% to ~10%.
2. A "Next match" button (→ H2): second match from 45% to 60%.

The full report with tables, charts and method: report.html in this folder (opens from disk).
"""

# --------------------------------------------------------------------------- Russian

BODY_RU = """<!-- Example of a full review: every block of the fixed skeleton and every component. Numbers are made up. -->
<div class="wrap">

<header class="masthead">
  <p class="eyebrow">Полный разбор · Пример · 1.0.8 и 1.1.0 · {{meta:window}}</p>
  <h1>{{meta:title}}</h1>
  <p class="standfirst">{{meta:subtitle}}</p>
</header>

<nav class="toc">
  <a href="#summary"><b>1</b>Краткая информация</a>
  <a href="#product"><b>2</b>Продуктовые метрики</a>
  <a href="#revenue"><b>3</b>Метрики дохода</a>
  <a href="#tech"><b>4</b>Технические данные</a>
  <a href="#countries"><b>5</b>Страны</a>
  <a href="#hypotheses"><b>6</b>Гипотезы</a>
  <a href="#actions"><b>7</b>Рекомендации</a>
</nav>

<section class="block" id="summary">
<h2><span class="bn">1</span>Краткая информация</h2>
<p class="lede">Новые игроки 01–20.09 по версии первого запуска. Все числа выдуманы: пример показывает, как выглядит каждый блок.</p>

<h3 id="summary-metrics">Ключевые метрики по версиям</h3>
{{html:assets/keymetrics.html}}

<h3 id="summary-answers">Короткие ответы</h3>
<div class="answers">
  <div class="ans"><div class="q">Что изменила 1.1.0</div>
    <div><p><b>Первый матч доигрывают чаще, до второго доходит не больше игроков.</b> 74% против 62%, второй матч 45% против 52% (<a href="#product-core">2.3</a>).</p></div></div>
  <div class="ans"><div class="q">Где теряем новичков</div>
    <div><p><b>На первой покупке в обучении и в первые 30 секунд игры.</b> Уходит 21,2% и 11,3% (<a href="#product-dropoff">2.2</a>).</p>
    <p>Второй абзац внутри ответа тоже поддерживается.</p></div></div>
  <div class="ans"><div class="q">Окупается ли закупка</div>
    <div><p><b>Нет.</b> Игрок стоит $0,40, приносит $0,13 (<a href="#revenue-ua">3.3</a>).</p></div></div>
</div>
</section>

<section class="block" id="product">
<h2><span class="bn">2</span>Продуктовые метрики</h2>
<p class="lede">Всё про игру, кроме денег: приток и удержание, отвалы, первые матчи, поведение перед уходом.</p>

<h3 id="product-retention">2.1 Новые игроки и D1 по дням</h3>
<figure id="fig-daily">
  <div class="figbox">
    <div class="legend"><span><i class="sw s1"></i>Органика</span><span><i class="sw s2"></i>Закупка</span><span><i class="sw s-unk"></i>Без атрибуции</span></div>
    {{svg:assets/daily.svg}}
  </div>
  <figcaption>С 15.09 органика падает примерно в 2,5 раза, закупка начинается 17.09. Наведи на столбик — подсказка покажет разбивку.</figcaption>
</figure>
<figure id="fig-retention">
  <div class="figbox">
    <div class="legend"><span><i class="sw lk s-old"></i>Сборка 1.0.8</span><span><i class="sw lk s1"></i>Сборка 1.1.0</span></div>
    {{svg:assets/retention.svg}}
  </div>
  <figcaption>line: две серии с разрывом (None), маркеры, значение в конце линии, полоса и вертикальная отметка.</figcaption>
</figure>
<p class="note"><b>Предварительно.</b> Последние семь дней ещё догружаются: D1 за 19–20.09 может вырасти. .note стоит рядом с числом, которое он уточняет.</p>

<h3 id="product-dropoff">2.2 Отвалы по шагам и по времени</h3>
{{html:assets/dropoff.html}}
<figure>
  <div class="figbox">{{svg:assets/dropoff.svg}}</div>
  <figcaption>Больше всего уходит в первые 30 секунд активного времени; дальше потери ровные, 3–6% на интервал.</figcaption>
</figure>
<p class="interp"><b>Интерпретация.</b> Первая покупка в обучении требует денег, которых у новичка ещё нет: 21,2% не доходят до неё. Это чтение чисел, а не факт — его проверяет H1.</p>

<h3 id="product-core">2.3 Первые матчи</h3>
{{html:assets/ordinals.html}}
<figure>
  <div class="figbox">
    <div class="legend"><span><i class="sw s-old"></i>Версия 1.0.8 (нейтральный .s-old)</span><span><i class="sw s1"></i>Версия 1.1.0</span></div>
    {{svg:assets/matches.svg}}
  </div>
  <figcaption>grouped_bars: значения над столбиками, если помещаются. Распределения почти совпадают.</figcaption>
</figure>
<div class="tablebox">
<table>
  <thead><tr><th>Новые игроки</th><th class="n">1.0.8</th><th class="n">1.1.0</th><th class="n">Разница</th></tr></thead>
  <tbody>
    <tr><td>Игроков</td><td class="n">118</td><td class="n">94</td><td class="n">−24</td></tr>
    <tr><td>Доиграли первый матч</td><td class="n">62%</td><td class="n ok">74%</td><td class="n ok">+12 п. п.</td></tr>
    <tr><td>Начали второй матч</td><td class="n">52%</td><td class="n bad">45%</td><td class="n bad">−7 п. п.</td></tr>
    <tr><td>Время в игре, медиана</td><td class="n">5,3 мин</td><td class="n">5,4 мин</td><td class="n">+0,1</td></tr>
    <tr class="total"><td>Всего сессий</td><td class="n">342</td><td class="n">291</td><td class="n">−51</td></tr>
  </tbody>
</table>
</div>
<p class="tnote">.tnote под таблицей: когорты, окно, фильтры. td.n — числа, td.ok / td.bad — оценка, tr.total — итог.</p>
<p class="interp"><b>Интерпретация.</b> 1.1.0 перенесла потерю с первого матча на переход ко второму. Разница 7 п. п. на 94 игроках — направление, а не доказанный эффект.</p>

<h3 id="product-negative">2.4 Уходы после негативных событий</h3>
{{html:assets/leaving.html}}
<p class="interp"><b>Интерпретация.</b> После кражи сворачивают 46,7% — вдвое чаще, чем после нейтральной покупки (22,8%).</p>
<figure>
  <div class="figbox">
    {{svg:assets/reasons.svg}}
  </div>
  <figcaption>Каждый четвёртый ушедший свернул игру в течение 20 секунд после кражи.</figcaption>
</figure>
</section>

<section class="block" id="revenue">
<h2><span class="bn">3</span>Метрики дохода</h2>
<p class="lede">Реклама по форматам, плейсментам и сетям; концентрация дохода; закупка.</p>

<h3 id="revenue-ads">3.1 Реклама по плейсментам</h3>
<div class="tablebox">
<table>
  <thead><tr><th>Плейсмент</th><th class="n">Показов в выборке</th><th class="n">Показов, оценка</th><th class="n">На игрока</th><th class="n">eCPM, $</th></tr></thead>
  <tbody>
    <tr><td>Интерстишал после матча</td><td class="n">612</td><td class="n est">≈ 6&#8239;120</td><td class="n">2,9</td><td class="n">3,10</td></tr>
    <tr><td>Ревард: удвоить награду</td><td class="n">118</td><td class="n est">≈ 1&#8239;180</td><td class="n">0,6</td><td class="n ok">6,40</td></tr>
    <tr><td>Ревард: второй шанс</td><td class="n">31</td><td class="n est">≈ 310</td><td class="n">0,1</td><td class="n">5,90</td></tr>
    <tr class="total"><td>Всего</td><td class="n">761</td><td class="n est">≈ 7&#8239;610</td><td class="n">3,6</td><td class="n">3,72</td></tr>
  </tbody>
</table>
</div>
<p class="tnote">≈ — оценка из выборки 10% устройств (× 10), курсив .est. Доли и средние на игрока не пересчитываются.</p>
<figure>
  <div class="figbox">
    LEGEND_NETWORKS
    {{svg:assets/networks.svg}}
  </div>
  <figcaption>Шесть категориальных цветов по порядку. Больше шести серий не бывает: остальное сворачивается в «прочее».</figcaption>
</figure>

<h3 id="revenue-concentration">3.2 Доход сосредоточен у немногих</h3>
<figure>
  <div class="figbox">
    <div class="legend"><span><i class="sw s2"></i>Пятеро лучших</span><span><i class="sw s1"></i>Остальные</span></div>
    {{svg:assets/revenue.svg}}
  </div>
  <figcaption>Среднее тянут вверх пятеро игроков; медиана в несколько раз ниже.</figcaption>
</figure>

<h3 id="revenue-ua">3.3 Закупка</h3>
<div class="calc">Порог окупаемости по доходу с игрока (пример):
  цена $0,40, ROAS 100%  →  нужно $0,40 с игрока   (сейчас $0,13, ×3,1)
  цена $0,40, ROAS 50%   →  нужно $0,20            (×1,5)</div>
<figure>
  <div class="figbox">
    <div class="legend"><span><i class="sw s-good"></i>В плюсе (.s-good)</span><span><i class="sw s-bad"></i>В минусе (.s-bad)</span></div>
    {{svg:assets/margin.svg}}
  </div>
  <figcaption>bar с отрицательными значениями: столбик растёт от нуля вниз, скруглён только конец с данными.</figcaption>
</figure>
<div class="shot"><p class="tag">Консоль · все страны · 17–20.09</p>
  <div class="frame"><img alt="Вымышленный скриншот консоли: пять синих столбиков на белой карточке" src="{{img:assets/console.png}}"></div>
  <p class="tnote">Что видно на скриншоте и чего на нём нет.</p></div>
<div class="shots2">
  <div class="shot"><p class="tag">Консоль · США · 17–20.09</p><div class="frame"><img alt="Вымышленный скриншот: оранжевые столбики" src="{{img:assets/console_a.png}}"></div></div>
  <div class="shot"><p class="tag">Консоль · США · 21.09</p><div class="frame"><img alt="Вымышленный скриншот: зелёные столбики" src="{{img:assets/console_b.png}}"></div></div>
</div>
</section>

<section class="block" id="tech">
<h2><span class="bn">4</span>Технические данные</h2>
<p class="lede">Техпроблемы и ошибки отправки аналитики. .cards: .hot — потеря, .adc — реклама, .okc — хорошо.</p>
<div class="cards">
  <div class="card hot" id="tech-duplicates"><div class="cnt">38%<em>событий</em></div><h4>Дубли дохода</h4><p>Одно начисление приходит двумя событиями: суммы по экономике завышены вдвое.</p></div>
  <div class="card adc" id="tech-timeouts"><div class="cnt">346<em>ошибок</em></div><h4>Ложные таймауты рекламы</h4><p>342 из них — реальные показы в ту же секунду.</p></div>
  <div class="card okc"><div class="cnt">60<em>FPS</em></div><h4>Производительность в норме</h4><p>Карточка .okc.</p></div>
  <div class="card"><h4>Мелочи в телеметрии</h4><p>Карточка без числа и без модификатора; <code>AdImpression</code> как код.</p></div>
</div>
</section>

<section class="block" id="countries">
<h2><span class="bn">5</span>Страны</h2>
<p class="lede">Разрез по странам в одном месте.</p>
<div class="tablebox">
<table>
  <thead><tr><th>Страна</th><th class="n">Игроков</th><th class="n">D1</th><th class="n">Время, медиана</th><th class="n">ARPU, $</th><th class="n">Доля дохода</th></tr></thead>
  <tbody>
    <tr><td>США</td><td class="n">81</td><td class="n ok">38,3%</td><td class="n">6,1 мин</td><td class="n ok">0,031</td><td class="n">71%</td></tr>
    <tr><td>Бразилия</td><td class="n">64</td><td class="n">31,1%</td><td class="n">5,0 мин</td><td class="n">0,004</td><td class="n">9%</td></tr>
    <tr><td>Индия</td><td class="n">67</td><td class="n bad">27,4%</td><td class="n">4,6 мин</td><td class="n bad">0,002</td><td class="n">5%</td></tr>
    <tr class="total"><td>Все</td><td class="n">212</td><td class="n">32,8%</td><td class="n">5,3 мин</td><td class="n">0,013</td><td class="n">100%</td></tr>
  </tbody>
</table>
</div>
</section>

<section class="block" id="hypotheses">
<h2><span class="bn">6</span>Гипотезы</h2>
<p class="lede">Что, по-нашему, происходит. Каждая гипотеза стоит на числах из блоков 2–5 и говорит, как её проверить.</p>
<div class="hyps">
  <article class="hyp" id="h1">
    <p class="hid">H1 <span class="conf high">уверенность высокая</span></p>
    <h4>Первая покупка в обучении слишком дорогая</h4>
    <p class="basis"><b>Опора:</b> на шаге «первая покупка» уходит 21,2% дошедших (<a href="#product-dropoff">2.2</a>).</p>
    <p class="test"><b>Как проверить:</b> дать стартовые деньги на покупку; гипотеза подтверждена, если потеря на шаге упадёт ниже 10% при n ≥ 150.</p>
  </article>
  <article class="hyp" id="h2">
    <p class="hid">H2 <span class="conf mid">уверенность средняя</span></p>
    <h4>После первого матча игроку не предлагают следующий шаг</h4>
    <p class="basis"><b>Опора:</b> второй матч начинают 45% против 52% (<a href="#product-core">2.3</a>); уходят сразу после экрана результатов (<a href="#product-negative">2.4</a>).</p>
    <p class="test"><b>Как проверить:</b> доля начавших второй матч ≥ 60% в новой сборке на тех же странах.</p>
  </article>
  <article class="hyp" id="h3">
    <p class="hid">H3 <span class="conf low">уверенность низкая</span></p>
    <h4>Закупка в США может окупиться только через реварды</h4>
    <p class="basis"><b>Опора:</b> eCPM реварда 6,40 против 3,10 у интерстишала (<a href="#revenue-ads">3.1</a>), игрок стоит $0,40 (<a href="#revenue-ua">3.3</a>).</p>
    <p class="test"><b>Как проверить:</b> ARPU за 7 дней ≥ $0,40 у закупленной когорты после добавления ревардов.</p>
  </article>
</div>
</section>

<section class="block" id="actions">
<h2><span class="bn">7</span>Рекомендации</h2>
<p class="lede">По убыванию отдачи. .acts нумерует их сам.</p>
<div class="acts">
  <div class="act"><div><h4>Дать стартовые деньги на первую покупку</h4>
    <p>Начислять сумму первой покупки при входе в обучение.</p>
    <p class="eff"><b>Ожидаемый эффект:</b> потеря на шаге «первая покупка» с 21% до ~10%, +20 игроков из 212 доходят до игры.</p>
    <p class="measure"><b>Как мерить:</b> ga.py dropoff по новой сборке через неделю, n ≥ 150.</p>
    <p class="why">→ <a href="#h1">H1</a></p></div></div>
  <div class="act"><div><h4>Кнопка «Следующий матч» на экране результатов</h4>
    <p>Главная кнопка — следующий матч; гараж вторым.</p>
    <p class="eff"><b>Ожидаемый эффект:</b> начавших второй матч с 45% до 60%.</p>
    <p class="measure"><b>Как мерить:</b> доля начавших второй матч среди доигравших первый, новые игроки.</p>
    <p class="why">→ <a href="#h2">H2</a></p></div></div>
  <div class="act"><div><h4>Закупать ради измерений, а не дохода</h4>
    <p>Небольшой бюджет на каждую сборку, одна страна.</p>
    <p class="eff"><b>Ожидаемый эффект:</b> 40 новых игроков на сборку за $16 — сравнение сборок без органического шума.</p>
    <p class="measure"><b>Как мерить:</b> ключевые метрики блока 1 по версиям.</p>
    <p class="why">→ <a href="#h3">H3</a></p></div></div>
</div>
</section>

<section class="block" id="data">
<h2>Какие данные нужны</h2>
<ul class="tight">
  <li><b>Консоль → Отчёты → По дням:</b> расход и установки за окно отчёта.</li>
  <li><b>Стор → Статистика страницы:</b> посетители и конверсия страницы по дням.</li>
</ul>
</section>

<section class="method" id="method">
  <h2>Методика</h2>
  <ul class="tight">
    <li>Отчёт {{meta:version_label}} «{{meta:title}}», собран {{meta:built_date}}. Окно данных {{meta:window}}.</li>
    <li>Источники: {{meta:sources_used}}. Вопрос: {{meta:question}}</li>
    <li>Таблицы блоков 1 и 2.2 — <code>ga.py keymetrics</code> и <code>ga.py dropoff --format html</code>, графики — <code>gak.report.charts</code>, сборка — <code>py analytics/ga.py report build sample</code>.</li>
  </ul>
</section>

</div>
"""


CHANGES_V2_RU = """</header>

<p class="note"><b>Что изменилось с v001.</b> Окно данных продлено до 21.09, строка ROAS в 3.3 пересчитана. Остальное как было.</p>
"""


QUESTION_BODY_RU = """<!-- Example of a question report: blocks 1, 3, 6, 7 and the method. Numbers are made up. -->
<div class="wrap">

<header class="masthead">
  <p class="eyebrow">Вопрос · Пример · закупка в США · {{meta:window}}</p>
  <h1>{{meta:title}}</h1>
  <p class="standfirst">{{meta:subtitle}}</p>
</header>

<section class="block" id="summary">
<h2><span class="bn">1</span>Краткая информация</h2>
<div class="tiles">
  <div class="tile ad"><p class="k">Цена игрока</p><div class="v">$0,40</div><p class="n">расход / 39 игроков · .tile.ad</p></div>
  <div class="tile"><p class="k">Доход с игрока</p><div class="v">$0,13</div><p class="n">n = 39 · .tile — нейтрально</p></div>
  <div class="tile warn"><p class="k">ROAS</p><div class="v">33% → 5%</div><p class="n">CPI → tROAS · .tile.warn</p></div>
  <div class="tile good"><p class="k">Доход в день установки</p><div class="v">80%</div><p class="n">n = 39 · .tile.good</p></div>
</div>
<h3 id="summary-answers">Короткие ответы</h3>
<div class="answers">
  <div class="ans"><div class="q">Окупается ли закупка в США</div>
    <div><p><b>Нет.</b> Игрок стоит $0,40, приносит $0,13, и 80% дохода приходит в день установки (<a href="#revenue-payback">3.1</a>).</p></div></div>
</div>
</section>

<section class="block" id="revenue">
<h2><span class="bn">3</span>Метрики дохода</h2>
<p class="lede">В вопросном отчёте остаются только нужные блоки, с теми же номерами и в том же порядке.</p>
<h3 id="revenue-payback">3.1 Окупаемость</h3>
<div class="calc">$15,60 расхода / 39 игроков = $0,40 за игрока
доход $5,07 / 39 = $0,13 за игрока → ROAS 33%</div>
<figure>
  <div class="figbox">
    <div class="legend"><span><i class="sw s2"></i>Пятеро лучших</span><span><i class="sw s1"></i>Остальные</span></div>
    {{svg:assets/revenue.svg}}
  </div>
  <figcaption>Доход держится на пятерых игроках из 39; медиана $0,04.</figcaption>
</figure>
<p class="interp"><b>Интерпретация.</b> Без ценных игроков в выборке ставка на ROAS не находит, кого покупать.</p>
</section>

<section class="block" id="hypotheses">
<h2><span class="bn">6</span>Гипотезы</h2>
<div class="hyps">
  <article class="hyp" id="h1">
    <p class="hid">H1 <span class="conf high">уверенность высокая</span></p>
    <h4>Доход с игрока ниже цены игрока втрое при любой стратегии ставок</h4>
    <p class="basis"><b>Опора:</b> $0,13 против $0,40 (<a href="#revenue-payback">3.1</a>).</p>
    <p class="test"><b>Как проверить:</b> ARPU за 7 дней у следующей закупленной когорты ≥ $0,40.</p>
  </article>
</div>
</section>

<section class="block" id="actions">
<h2><span class="bn">7</span>Рекомендации</h2>
<div class="acts">
  <div class="act"><div><h4>Остановить закупку на доход</h4>
    <p>Оставить небольшой бюджет только для сравнения сборок.</p>
    <p class="eff"><b>Ожидаемый эффект:</b> минус $50 убытка в день.</p>
    <p class="measure"><b>Как мерить:</b> дневная маржа закупки в следующем отчёте.</p>
    <p class="why">→ <a href="#h1">H1</a></p></div></div>
</div>
</section>

<section class="method" id="method">
  <h2>Методика</h2>
  <ul class="tight">
    <li>Отчёт {{meta:version_label}}, собран {{meta:built_date}}. Окно данных {{meta:window}}. Все числа выдуманы.</li>
  </ul>
</section>

</div>
"""


MD_RU = """# Пример 1.0.8 и 1.1.0, 01–20.09: полный разбор

{until} · sample {label} · все числа вымышлены

Новички уходят на первой покупке в обучении, а закупка не окупается ни при какой ставке.

**Коротко**
- 1.1.0: первый матч доигрывают чаще (74% против 62%), второй начинают реже (45% против 52%), n = 94 / 118.
- Главные потери: первая покупка в обучении (21,2%) и первые 30 секунд игры (11,3%), n = 212.
- Закупка: игрок стоит $0,40, приносит $0,13.

**Гипотезы**
- H1 — первая покупка слишком дорогая (высокая).
- H2 — после первого матча нет следующего шага (средняя).

**Что делать**
1. Стартовые деньги на первую покупку (→ H1): потеря на шаге с 21% до ~10%.
2. Кнопка «Следующий матч» (→ H2): второй матч с 45% до 60%.

Полный отчёт с таблицами, графиками и методикой — report.html в этой папке (открывается с диска).
"""

# --------------------------------------------------------------------------- per language

TEXT = {
    "en": {
        "body": BODY_EN, "changes": CHANGES_V2_EN, "question_body": QUESTION_BODY_EN, "md": MD_EN,
        "title": "Sample 1.0.8 and 1.1.0, Sep 1–20: full review",
        "subtitle": "New players leave at the first purchase in the tutorial, and paid UA does not pay back at any bid",
        "question": "Full review of Sep 1–20: what 1.1.0 changed, where new players leave, whether paid UA pays back",
        "sources": ["made-up data", "placeholder screenshots"],
        "q_title": "Sample: does paid UA pay back in the US",
        "q_subtitle": "No: a player costs three times what they bring",
        "q_question": "Does paid UA pay back in the US?",
        "q_sources": ["made-up data"],
        "until_v1": "2026-09-20", "until_v2": "2026-09-21",
        "network": "Network",
        "steps": ["Loading: SDK", "Loading: ads", "First scene", "Tutorial: first step", "Tutorial: first purchase"],
        "ordinals": ["Hero purchase", "Theft"],
        "leaving": ["Hero stolen", "Got hit", "Interstitial started", "Hero purchase (neutral)"],
        "eff_prefix": '<p class="eff"><b>Expected effect:</b> the loss',
        "eff_broken": '<p><b>Effect:</b> the loss',
        "conf_low": '<span class="conf low">confidence low</span>',
        "why_broken": '<p class="why">→ section 3</p>',
        "scaffold_word": "Product metrics",
        "needles": ["Lost, % of previous", "Step time, s", "N in session", "Backgrounded within 20 s",
                    "Never came back", "Reports", ">draft<", "full review", ">question<"],
        "charts": {
            "day": lambda d: f"Sep {d}",
            "band": "from Sep 15: new build (example)",
            "organic": "Organic", "paid": "Paid", "unknown": "Unattributed",
            "daily_title": "New players per day by source (example)",
            "daily_x": "September, day of month · made-up data",
            "build": "Build",
            "matches_title": "How many matches a new player started (example)",
            "matches_x": "matches started over the lifetime · share of new players · made-up data",
            "weeks": ["week 1", "week 2", "week 3"],
            "networks_title": "Share of revenue by ad network (example)",
            "networks_x": "six series: the whole categorical palette .s1–.s6 in order · made-up data",
            "player": "player",
            "revenue_title": "Revenue per player, descending (example)",
            "revenue_x": "39 made-up players, ad revenue, descending",
            "reasons": ["Backgrounded the game within 20 s of a theft", "Left to the menu mid-match",
                        "Restarted after losing a race", "Doubled a reward with an ad and left",
                        "Pressed nothing: the last event is a level load, long and without a progress bar"],
            "reasons_title": "What a player does before leaving (example)",
            "reasons_x": "share of new players who left · a long label is clipped, the tooltip has the full text",
            "margin_title": "Daily UA margin (example)",
            "margin_x": "revenue minus spend per day · made-up data",
            "switch": "switch", "ua_start": "UA starts",
            "retention_title": "D1 by install day (example)",
            "retention_x": "share who came back the next day · made-up data",
        },
    },
    "ru": {
        "body": BODY_RU, "changes": CHANGES_V2_RU, "question_body": QUESTION_BODY_RU, "md": MD_RU,
        "title": "Пример 1.0.8 и 1.1.0, 01–20.09: полный разбор",
        "subtitle": "Новички уходят на первой покупке в обучении, а закупка не окупается ни при какой ставке",
        "question": "Полный разбор игры за 01–20.09: что изменила 1.1.0, где теряем новичков, окупается ли закупка",
        "sources": ["вымышленные данные", "скриншоты-заглушки"],
        "q_title": "Пример: окупается ли закупка в США",
        "q_subtitle": "Нет: игрок стоит втрое больше, чем приносит",
        "q_question": "Окупается ли закупка в США?",
        "q_sources": ["вымышленные данные"],
        "until_v1": "20.09.2026", "until_v2": "21.09.2026",
        "network": "Сеть",
        "steps": ["Загрузка: SDK", "Загрузка: реклама", "Первая сцена", "Обучение: первый шаг",
                  "Обучение: первая покупка"],
        "ordinals": ["Покупка героя", "Кража"],
        "leaving": ["Украли героя", "Получил удар", "Старт интерстишала", "Покупка героя (нейтральное)"],
        "eff_prefix": '<p class="eff"><b>Ожидаемый эффект:</b> потеря',
        "eff_broken": '<p><b>Эффект:</b> потеря',
        "conf_low": '<span class="conf low">уверенность низкая</span>',
        "why_broken": '<p class="why">→ раздел 3</p>',
        "scaffold_word": "Продуктовые метрики",
        "needles": ["Ушло, % от предыдущего", "Время шага, с", "№ в сессии", "Свернули за 20 с",
                    "Не вернулись вовсе", "Отчёты", "черновик", "полный разбор", ">вопрос<"],
        "charts": {
            "day": lambda d: f"{d:02d}.09",
            "band": "с 15.09: новая версия (пример)",
            "organic": "Органика", "paid": "Закупка", "unknown": "Без атрибуции",
            "daily_title": "Новые игроки по дням и источникам (пример)",
            "daily_x": "сентябрь, день месяца · вымышленные данные",
            "build": "Сборка",
            "matches_title": "Сколько матчей начал новый игрок (пример)",
            "matches_x": "матчей начато за всё время · доля новых игроков · вымышленные данные",
            "weeks": ["неделя 1", "неделя 2", "неделя 3"],
            "networks_title": "Доля дохода по рекламным сетям (пример)",
            "networks_x": "шесть серий: весь категориальный ряд .s1–.s6 по порядку · вымышленные данные",
            "player": "игрок",
            "revenue_title": "Доход с каждого игрока по убыванию (пример)",
            "revenue_x": "39 вымышленных игроков, доход с рекламы, по убыванию",
            "reasons": ["Свернул игру в течение 20 с после кражи", "Вышел в меню посреди матча",
                        "Рестарт после поражения в гонке", "Удвоил награду за рекламу и ушёл",
                        "Ничего не нажал: последнее событие — загрузка уровня, долгая и без прогресс-бара"],
            "reasons_title": "Что делает игрок перед уходом (пример)",
            "reasons_x": "доля ушедших новичков · длинная подпись обрезана, полный текст во всплывающей подсказке",
            "margin_title": "Дневная маржа закупки (пример)",
            "margin_x": "доход минус расход за день · вымышленные данные",
            "switch": "переход", "ua_start": "старт закупки",
            "retention_title": "D1 по дню установки (пример)",
            "retention_x": "доля вернувшихся на следующий день · вымышленные данные",
        },
    },
}
