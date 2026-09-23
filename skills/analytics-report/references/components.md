# Components

`report.src.html` is a body fragment; the builder wraps it with `theme.css` into a full
page (`report.html`) and a shell-less copy (`artifact.html`). Class names below are the
API of `analytics/kit/gak/report/theme.css`; everything is responsive down to 400 px and
works in light and dark themes. Do not add inline colours or `<style>` blocks — use the
semantic classes so both themes stay readable. Start from the scaffold that
`report new --kind full|question` writes (its comments list the placeholders; HTML comments
are dropped at build) and fill or delete every TODO — the build warns about leftovers.

The skeleton itself is checked at build: blocks as `<section id="...">` in order, unique
ids, every `#link` resolving, hypotheses with a confidence mark and an evidence link,
recommendations with a hypothesis link, `.eff` and `.measure`.

## Page and masthead

```html
<div class="wrap">
<header class="masthead">
  <p class="eyebrow">Полный разбор · MyGame · 0.2.0 · {{meta:window}}</p>
  <h1>MyGame 0.2.0, 08–21.09: полный разбор</h1>          <!-- the request, as asked -->
  <p class="standfirst">{{meta:subtitle}}</p>             <!-- the thesis, from meta.json -->
</header>
…blocks…
</div>
```

## What changed since vK (new versions only, right after the masthead)

```html
<p class="note"><b>Что изменилось с v001.</b> Данные до 21.09; блок 2.2 пересчитан (потеря на
загрузке 11,9% → 6,8%: считали по сессиям, а не по запускам); добавлена H4.</p>
```

## Table of contents (full review)

```html
<nav class="toc">
  <a href="#summary"><b>1</b>Краткая информация</a>
  <a href="#product"><b>2</b>Продуктовые метрики</a>
  … one link per block present …
</nav>
```

## Blocks

Every block is a `section.block` with its fixed id and number:

```html
<section class="block" id="revenue">
<h2><span class="bn">3</span>Метрики дохода</h2>
<p class="lede">The claim of the block in one sentence.</p>
<h3 id="revenue-ads">3.1 Реклама по форматам и плейсментам</h3>
…table / figure / interpretation…
</section>
```

Ids: `summary` (1), `product` (2), `revenue` (3), `tech` (4), `countries` (5),
`hypotheses` (6), `actions` (7), then `data` (optional) and the method as
`<section class="method" id="method">`. Sub-sections: `h3` with an id prefixed by the block
(`product-dropoff`, `revenue-ads`, `tech-duplicates`) and a number `2.2`, `3.1` — the
anchors hypotheses and short answers link to.

## Block 1: key metrics and short answers

```html
<section class="block" id="summary">
<h2><span class="bn">1</span>Краткая информация</h2>
<p class="lede">Новые игроки 08–21.09 по версии первого запуска.</p>
<h3 id="summary-metrics">Ключевые метрики по версиям</h3>
{{html:assets/keymetrics.html}}          <!-- ga.py keymetrics --format html --out ... -->
<h3 id="summary-answers">Короткие ответы</h3>
<div class="answers">
  <div class="ans"><div class="q">Где теряем новичков</div>
    <div><p><b>На первой покупке в обучении.</b> Уходит 21,2% дошедших, n = 179 (<a href="#product-dropoff">2.2</a>).</p></div></div>
</div>
</section>
```

The key-metrics fragment is a `.tablebox` with `table.kpi` (versions as columns, the all-
players column last; `n` and medians in `<small>`; estimate rows `tr.est` / `td.n.est`
with ≈) and a `.tnote` with the definitions. Do not retype it by hand: regenerate it.

In a question report block 1 may hold 3–4 tiles instead of the table:

```html
<div class="tiles">
  <div class="tile warn"><p class="k">Застряли в загрузке</p><div class="v">6,8%</div>
    <p class="n">n = 980 новых · 01–21.09</p></div>
  <div class="tile ad"><p class="k">Доход с рекламы на игрока</p><div class="v">$0,0051</div><p class="n">…</p></div>
  <div class="tile good"><p class="k">…</p><div class="v">…</div><p class="n">…</p></div>
</div>
```

`.k` label, `.v` value, `.n` qualifier (n, window, filter). Variants `.warn` (loss), `.ad`
(paid/ads), `.good` (revenue, improvement), none = neutral.

## Drop-off (block 2)

```html
<h3 id="product-dropoff">2.2 Отвалы по шагам и по времени</h3>
{{html:assets/dropoff.html}}           <!-- ga.py dropoff --steps … --format html --out … --svg … -->
<figure>
  <div class="figbox">{{svg:assets/dropoff.svg}}</div>
  <figcaption>Больше всего уходит в первые 30 секунд; дальше 3–6% на интервал.</figcaption>
</figure>
```

The fragment has two `table.drop` (steps, then active time; the three biggest losses in
`td.bad`; step time median · p90 · max when the steps view has `sec`) and a `.tnote` with
the cohort and the definitions.

## Core actions and leaving after events (block 2)

```html
<h3 id="product-core">2.3 Ядро: действия по номеру в сессии</h3>
{{html:assets/ordinals.html}}        <!-- ga.py ordinals --events ... --format html --out ... -->
<h3 id="product-negative">2.4 Уходы после негативных событий</h3>
{{html:assets/leaving.html}}         <!-- ga.py leaving --events ...,<neutral> --pause ... -->
<p class="interp"><b>Интерпретация.</b> После кражи сворачивают вдвое чаще, чем после покупки.</p>
```

`ordinals` writes one `table.drop.ord` per action (N, devices, % of the cohort, median and
mean time into the session); `leaving` one table (event, devices with it, backgrounded, back,
nothing else, never came back; counts in `<small>`).

## Interpretation

```html
<p class="interp"><b>Интерпретация.</b> Покупка требует денег, которых у новичка ещё нет —
это чтение чисел выше, его проверяет H1.</p>
```

Everything that explains *why* goes here; plain paragraphs, tables and charts state facts.

## Figure with chart

```html
<figure id="fig-d1">
  <div class="figbox">
    <div class="legend"><span><i class="sw s1"></i>Paid</span><span><i class="sw s2"></i>Organic</span></div>
    {{svg:assets/first_session_funnel.svg}}
  </div>
  <figcaption>The biggest drop is between "finished 1st" and "started 2nd".</figcaption>
</figure>
```

The legend line is what `charts.legend_html([(label, css_class), ...])` returns; one
series needs no legend.

## Table

```html
<div class="tablebox">
<table>
  <thead><tr><th>Плейсмент</th><th class="n">Показов в выборке</th><th class="n">Показов, оценка</th><th class="n">eCPM, $</th></tr></thead>
  <tbody>
    <tr><td>Интерстишал после матча</td><td class="n">612</td><td class="n est">≈ 12&#8239;240</td><td class="n">1,07</td></tr>
    <tr><td>Ревард: удвоить награду</td><td class="n">118</td><td class="n est">≈ 2&#8239;360</td><td class="n ok">2,20</td></tr>
    <tr class="total"><td>Всего</td><td class="n">730</td><td class="n est">≈ 14&#8239;600</td><td class="n">1,26</td></tr>
  </tbody>
</table>
</div>
<p class="tnote">≈ — оценка из выборки 5% устройств (× 20); eCPM и доли не пересчитываются.</p>
```

`td.n` numeric, `td.bad` / `td.ok` only where the colour carries the point, `tr.total`
totals, `td.est` / `.est` an estimate scaled from a device sample.

## Note and calculation

```html
<p class="note"><b>Предварительно.</b> 19–21.09 ещё догружаются; D1 за 20.09 может вырасти.</p>
<div class="calc">Required ARPU = CPI × target ROAS = $0,40 × 100% = $0,40; actual $0,036 → gap ×11</div>
```

## Screenshots

```html
<div class="shot"><p class="tag">AdMob · Country = US · 20–23.08.2026 · Pacific time</p>
  <div class="frame"><img alt="AdMob ad units report, US, key numbers" src="{{img:assets/admob_us_units.png}}"></div>
  <p class="tnote">Estimated earnings per ad unit; mediation networks are not included.</p></div>

<div class="shots2">
  <div class="shot">…</div>
  <div class="shot">…</div>
</div>
```

## Cards (technical findings, defects, segments)

```html
<div class="cards">
  <div class="card hot" id="tech-duplicates"><div class="cnt">61<em>% событий</em></div><h4>Дубли дохода</h4>
    <p>Одно начисление приходит двумя событиями; экономика по событиям завышена вдвое.</p></div>
  <div class="card adc"><div class="cnt">8<em>%</em></div><h4>Rewarded show rate</h4><p>…</p></div>
  <div class="card okc"><div class="cnt">$0,054</div><h4>US organic ARPU</h4><p>…</p></div>
</div>
```

`.hot` = problem, `.adc` = ads/paid, `.okc` = good. `.cnt` is the headline number, an
optional `<em>` inside it holds the unit. Give a card an id when a hypothesis cites it.

## Hypotheses (block 6)

```html
<section class="block" id="hypotheses">
<h2><span class="bn">6</span>Гипотезы</h2>
<div class="hyps">
  <article class="hyp" id="h1">
    <p class="hid">H1 <span class="conf high">уверенность высокая</span></p>
    <h4>Первая покупка в обучении слишком дорогая</h4>
    <p class="basis"><b>Опора:</b> на шаге «первая покупка» уходит 21,2% дошедших (<a href="#product-dropoff">2.2</a>).</p>
    <p class="test"><b>Как проверить:</b> стартовые деньги на покупку; подтверждено, если потеря на шаге < 10% при n ≥ 150.</p>
  </article>
</div>
</section>
```

Ids `h1`, `h2`… in order. Confidence: `.conf.high` / `.mid` / `.low` (the dots are drawn by
the theme; the text says it in words). The basis links to at least one section of blocks
2–5; the test names a metric and a threshold.

## Recommendations (block 7)

```html
<section class="block" id="actions">
<h2><span class="bn">7</span>Рекомендации</h2>
<p class="lede">По убыванию отдачи.</p>
<div class="acts">
  <div class="act"><div><h4>Дать стартовые деньги на первую покупку</h4>
    <p>Начислять сумму первой покупки при входе в обучение.</p>
    <p class="eff"><b>Ожидаемый эффект:</b> потеря на шаге с 21% до ~10%.</p>
    <p class="measure"><b>Как мерить:</b> ga.py dropoff по новой версии через неделю, n ≥ 150.</p>
    <p class="why">→ <a href="#h1">H1</a></p></div></div>
</div>
</section>
```

Numbering comes from the stylesheet; order by payoff. A tracking fix belongs here too —
give it a hypothesis in block 6 ("H4: duplicated income events double the economy
numbers") so it has a measurable reason.

## Data requests and method

```html
<section class="block" id="data">
<h2>Какие данные нужны</h2>
<ul class="tight">
  <li><b>Google Ads → Campaigns → Segment → Time → Day → Download (CSV):</b> spend and
    Installs for 24–28.08, all campaigns — closes the ROI period.</li>
</ul>
</section>

<section class="method" id="method">
  <h2>Методика</h2>
  <ul class="tight">
    <li>{{meta:version_label}}, {{meta:built_date}}. Окно данных {{meta:window}}, часовой пояс приложения UTC+3.</li>
    <li>AppMetrica Logs API, выгрузка 21.09 15:40; выборка 5% устройств (абсолютные числа × 20, помечены ≈).</li>
    <li>Исключены девайсы разработки (правило в notes/project.md). D1 — событие на следующий календарный день; активное время — паузы внутри сессии, каждая не больше 600 с.</li>
  </ul>
</section>
```

Many data requests with several attributes each can be a `.tablebox` table with columns
*what · where exactly · range and filters · why*.
