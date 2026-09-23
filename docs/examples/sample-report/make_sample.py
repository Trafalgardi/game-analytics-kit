"""Build the live examples of the report package and check what they produced.

    py docs/examples/sample-report/make_sample.py

Uses gak.report exactly like the CLI does: new_version -> write body and assets -> build.
Two reports on made-up numbers, both in the fixed skeleton of DESIGN.md section 6:

    sample            a full review (kind "full"): v001, v002 made with from_version=1, v003 a draft
    sample-question   a question report (kind "question"): v001

The key-metrics and drop-off tables are rendered by gak.metrics from made-up results, the
same code `ga.py keymetrics / dropoff --format html` runs. Output: analytics/reports/ next to
this file. The script then validates the output: tags balance, no placeholders left, sane
sizes, artifact.html without a document shell, every component present, and that the
builder refuses what it must refuse (placeholders, structure). Exit code 0 = all passed.
"""
from __future__ import annotations

import json
import re
import shutil
import sqlite3
import struct
import sys
import tempfile
import zlib
from html.parser import HTMLParser
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "kit"))

from gak import metrics, sequences  # noqa: E402
from gak.report import ReportError, build, build_index, charts as ch, new_version  # noqa: E402

ANALYTICS = HERE / "analytics"
SLUG = "sample"
QSLUG = "sample-question"
LANG = "ru"


# --------------------------------------------------------------------------- fake inputs

def png(width: int, height: int, pixel) -> bytes:
    """Minimal RGB PNG writer: pixel(x, y) -> (r, g, b)."""
    rows = b"".join(b"\0" + bytes(c for x in range(width) for c in pixel(x, y)) for y in range(height))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    signature = bytes([137, 80, 78, 71, 13, 10, 26, 10])
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return signature + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(rows, 9)) + chunk(b"IEND", b"")


def fake_console(accent: tuple[int, int, int], bars: list[int]):
    """A pretend dashboard screenshot: title bar, card, a few columns."""
    def pixel(x, y):
        if y < 34:
            return (38, 42, 51)
        if 20 <= x < 620 and 54 <= y < 330:
            base_y = 310
            for i, h in enumerate(bars):
                x0 = 60 + i * 64
                if x0 <= x < x0 + 36 and base_y - h <= y < base_y:
                    return accent
            if y in (base_y, base_y - 80, base_y - 160) and 50 <= x < 600:
                return (225, 226, 230)
            return (255, 255, 255)
        return (241, 243, 246)
    return pixel


def fake_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE events (id INTEGER PRIMARY KEY, date TEXT, event_name TEXT);
        CREATE TABLE installations (id INTEGER PRIMARY KEY, date TEXT, publisher_name TEXT);
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
    """)
    con.executemany("INSERT INTO events (date, event_name) VALUES (?, ?)",
                    [(f"2026-09-{d:02d}", "level_start") for d in range(1, 22) for _ in range(d % 4 + 1)])
    con.executemany("INSERT INTO installations (date, publisher_name) VALUES (?, ?)",
                    [(f"2026-09-{d:02d}", "Google Ads" if d > 16 else "") for d in range(1, 22)])
    con.execute("INSERT INTO meta VALUES ('app_name', 'Sample Game')")
    con.execute("INSERT INTO meta VALUES ('appmetrica.sample_rate', '0.1')")
    con.commit()
    con.close()


# --------------------------------------------------------------------------- standard tables

def fake_population(n: int) -> metrics.Population:
    devices = {f"d{i}": metrics.Device("2026-09-01", "1.0.8" if i < 118 else "1.1.0", "US") for i in range(n)}
    return metrics.Population(devices, "v_players", "2026-09-01", "2026-09-20", 0.1, "2026-09-21")


def fake_key_metrics() -> metrics.KeyMetrics:
    g = ["1.0.8", "1.1.0", metrics.ALL]

    def row(key, unit, values, n=None, median=None, estimate=False):
        return metrics.Row(key, unit, dict(zip(g, values)), dict(zip(g, n or [])), dict(zip(g, median or [])),
                           estimate)
    rows = [
        row("players", "count", [118, 94, 212]),
        row("players_est", "count", [1180, 940, 2120], estimate=True),
        row("d1", "pct", [31.2, 35.1, 32.8], n=[109, 77, 186]),
        row("d3", "pct", [12.4, 14.0, 13.0], n=[97, 57, 154]),
        row("d7", "pct", [5.1, None, 5.1], n=[79, 0, 79]),
        row("playtime", "min", [11.8, 12.6, 12.2], median=[5.3, 5.4, 5.3]),
        row("sessions", "num", [2.9, 3.1, 3.0], median=[2, 2, 2]),
        row("session_len", "min", [4.1, 4.1, 4.1], median=[1.9, 2.0, 1.9]),
        row("ads_interstitial", "num", [3.4, 3.6, 3.5]),
        row("ads_rewarded", "num", [0.6, 0.9, 0.7]),
        row("arpu", "usd", [0.012, 0.015, 0.0133]),
        row("revenue", "usd", [1.42, 1.41, 2.83]),
        row("revenue_est", "usd", [14.2, 14.1, 28.3], estimate=True),
    ]
    return metrics.KeyMetrics("version", g, rows, fake_population(212), 600, None, [])


def fake_dropoff() -> metrics.Dropoff:
    total, rows = 212, []

    def chain(section, items):
        previous = total
        rows.append(metrics.DropRow(section, "", total, None, None, 100.0))
        for label, reached, seconds in items:
            lost = previous - reached
            rows.append(metrics.DropRow(section, label, reached, lost, 100.0 * lost / previous,
                                        100.0 * reached / total, seconds))
            previous = reached
    chain("steps", [("Загрузка: SDK", 207, None), ("Загрузка: реклама", 188, None), ("Первая сцена", 184, None),
                    ("Обучение: первый шаг", 179, None), ("Обучение: первая покупка", 141, None)])
    alive = [188, 171, 160, 151, 142, 136, 129, 125, 119, 110, 106, 101, 98, 95, 91, 88, 85, 83, 80, 78]
    chain("time", [(f"{t // 60}:{t % 60:02d}", a, t) for t, a in zip(range(30, 601, 30), alive)])
    timing = {"Загрузка: SDK": (0.4, 1.1, 38.0), "Загрузка: реклама": (7.8, 24.0, 3899.0),
              "Первая сцена": (10.7, 31.0, 1357.0)}
    for row in rows:
        if row.section == "steps" and row.label in timing:
            row.sec_median, row.sec_p90, row.sec_max = timing[row.label]
    return metrics.Dropoff(rows, fake_population(total), "all", 600, "v_first_steps", [])


def fake_ordinals() -> sequences.Ordinals:
    data = {"Покупка героя": ([180, 130, 95, 70, 51], [42, 145, 262, 364, 480], [140, 282, 489, 684, 908]),
            "Кража": ([150, 112, 83, 58, 41], [93, 211, 317, 410, 489], [230, 411, 645, 983, 1121])}
    rows = [sequences.OrdinalRow(label, n, dev, dev + n * 7, 100.0 * dev / 212, med, mean)
            for label, (devs, meds, means) in data.items()
            for n, (dev, med, mean) in enumerate(zip(devs, meds, means), 1)]
    return sequences.Ordinals(rows, fake_population(212), "Покупка героя, Кража", 5, False, [])


def fake_leaving() -> sequences.Leaving:
    rows = [sequences.LeavingRow("Украли героя", 190, 120, 56, 30, 25, 6),
            sequences.LeavingRow("Получил удар", 620, 150, 61, 34, 22, 2),
            sequences.LeavingRow("Старт интерстишала", 540, 131, 85, 43, 30, 1),
            sequences.LeavingRow("Покупка героя (нейтральное)", 700, 180, 41, 30, 0, 0)]
    return sequences.Leaving(rows, fake_population(212), "…", 20, ["app_pause"], ["app_resume"], [])


# --------------------------------------------------------------------------- charts

DAYS = [f"{d:02d}.09" for d in range(1, 22)]
ORGANIC = [26, 27, 25, 29, 24, 28, 27, 26, 30, 25, 27, 26, 28, 25, 11, 10, 9, 12, 10, 11, 9]
PAID = [0] * 16 + [7, 20, 14, 12, 31]
UNKNOWN = [2, 1, 3, 2, 2, 1, 2, 3, 1, 2, 2, 1, 3, 2, 1, 1, 4, 5, 3, 2, 7]
REVENUE = [1.17, 0.97, 0.76, 0.26, 0.23, 0.19, 0.16, 0.14, 0.12, 0.11, 0.1, 0.09, 0.08, 0.07, 0.06,
           0.06, 0.05, 0.05, 0.04, 0.04, 0.04, 0.04, 0.03, 0.03, 0.03, 0.02, 0.02, 0.02, 0.02, 0.01,
           0.01, 0.01, 0.01, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]


def make_charts() -> dict[str, str]:
    band = ch.annotate_band("15.09", None, "с 15.09: новая версия (пример)")
    margin = [-3.2, -1.5, 0.4, 2.1, -0.8, 1.6, 3.3, -2.4, 0.9, 1.2]
    return {
        "daily": ch.stacked_bars(
            DAYS, [("Органика", "s1", ORGANIC), ("Закупка", "s2", PAID), ("Без атрибуции", "s-unk", UNKNOWN)],
            bands=[band], lang=LANG, title="Новые игроки по дням и источникам (пример)",
            x_label="сентябрь, день месяца · вымышленные данные"),
        "matches": ch.grouped_bars(
            ["0", "1", "2", "3–5", "6–10", "11+"],
            [("Версия 1.0.8", "s-old", [16.2, 32.4, 13.2, 19.1, 13.2, 5.9]),
             ("Версия 1.1.0", "s1", [20.8, 34.0, 9.4, 20.8, 9.4, 5.7])],
            unit="%", lang=LANG, title="Сколько матчей начал новый игрок (пример)",
            x_label="матчей начато за всё время · доля новых игроков · вымышленные данные"),
        "networks": ch.grouped_bars(
            ["неделя 1", "неделя 2", "неделя 3"],
            [(f"Сеть {n}", f"s{i + 1}", vals) for i, (n, vals) in enumerate([
                ("A", [34, 31, 29]), ("B", [22, 24, 21]), ("C", [15, 14, 18]),
                ("D", [12, 13, 12]), ("E", [10, 11, 12]), ("F", [7, 7, 8])])],
            unit="%", lang=LANG, title="Доля дохода по рекламным сетям (пример)", height=260,
            x_label="шесть серий: весь категориальный ряд .s1–.s6 по порядку · вымышленные данные"),
        "revenue": ch.ranked_bars(
            REVENUE, labels=[f"игрок {i + 1}" for i in range(len(REVENUE))], highlight_top=5,
            mean_line=True, median_line=True, unit="$", lang=LANG,
            title="Доход с каждого игрока по убыванию (пример)",
            x_label="39 вымышленных игроков, доход с рекламы, по убыванию"),
        "reasons": ch.hbars(
            ["Свернул игру в течение 20 с после кражи", "Вышел в меню посреди матча",
             "Рестарт после поражения в гонке", "Удвоил награду за рекламу и ушёл",
             "Ничего не нажал: последнее событие — загрузка уровня, долгая и без прогресс-бара"],
            [25, 16, 9, 6, 3], unit="%", lang=LANG, highlight={0: "s-bad"},
            title="Что делает игрок перед уходом (пример)",
            x_label="доля ушедших новичков · длинная подпись обрезана, полный текст во всплывающей подсказке"),
        "margin": ch.bar(
            [f"{d:02d}.09" for d in range(12, 22)], margin, unit="$", lang=LANG,
            highlight={i: ("s-good" if v >= 0 else "s-bad") for i, v in enumerate(margin)},
            title="Дневная маржа закупки (пример)", x_label="доход минус расход за день · вымышленные данные"),
        "retention": ch.line(
            DAYS, [("Сборка 1.0.8", "s-old", [31, 30, 32, 29, 30, 31, 28, 30, 29, 31, 30, 29, 30, 31] + [None] * 7),
                   ("Сборка 1.1.0", "s1", [None] * 13 + [30, 33, 35, 34, 36, 35, 37, 36])],
            unit="%", lang=LANG, ymax=50, bands=[ch.annotate_band("14.09", "15.09", "переход")],
            annotations=[("17.09", "старт закупки")], title="D1 по дню установки (пример)",
            x_label="доля вернувшихся на следующий день · вымышленные данные"),
    }


# --------------------------------------------------------------------------- the full review

BODY = """<!-- Example of a full review: every block of the fixed skeleton and every component. Numbers are made up. -->
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

CHANGES_V2 = """</header>

<p class="note"><b>Что изменилось с v001.</b> Окно данных продлено до 21.09, строка ROAS в 3.3 пересчитана. Остальное как было.</p>
"""


# --------------------------------------------------------------------------- the question report

QUESTION_BODY = """<!-- Example of a question report: blocks 1, 3, 6, 7 and the method. Numbers are made up. -->
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


def write_assets(vdir: Path, names: list[str] | None = None) -> None:
    charts = make_charts()
    for name, svg in charts.items():
        if names is None or name in names:
            (vdir / "assets" / f"{name}.svg").write_text(svg, encoding="utf-8", newline="\n")
    if names is None:
        (vdir / "assets" / "keymetrics.html").write_text(
            metrics.render_key_metrics(fake_key_metrics(), "html", LANG), encoding="utf-8", newline="\n")
        (vdir / "assets" / "ordinals.html").write_text(
            sequences.render_ordinals(fake_ordinals(), "html", LANG), encoding="utf-8", newline="\n")
        (vdir / "assets" / "leaving.html").write_text(
            sequences.render_leaving(fake_leaving(), "html", LANG), encoding="utf-8", newline="\n")
        drop = fake_dropoff()
        (vdir / "assets" / "dropoff.html").write_text(metrics.render_dropoff(drop, "html", LANG),
                                                      encoding="utf-8", newline="\n")
        (vdir / "assets" / "dropoff.svg").write_text(metrics.dropoff_svg(drop, LANG), encoding="utf-8",
                                                     newline="\n")
        (vdir / "assets" / "console.png").write_bytes(png(640, 360, fake_console((42, 120, 214), [120, 180, 150, 210, 90])))
        (vdir / "assets" / "console_a.png").write_bytes(png(640, 360, fake_console((235, 104, 52), [60, 140, 200, 170, 110])))
        (vdir / "assets" / "console_b.png").write_bytes(png(640, 360, fake_console((12, 163, 12), [200, 90, 60, 150, 180])))


def write_body(vdir: Path) -> None:
    networks = ch.legend_html([(f"Сеть {n}", f"s{i + 1}") for i, n in enumerate("ABCDEF")])
    (vdir / "report.src.html").write_text(BODY.replace("LEGEND_NETWORKS", networks), encoding="utf-8", newline="\n")
    write_assets(vdir)


def write_md(vdir: Path, label: str, until: str) -> None:
    """report.md: the short version for chat and messengers."""
    text = f"""# Пример 1.0.8 и 1.1.0, 01–20.09: полный разбор

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
    (vdir / "report.md").write_text(text, encoding="utf-8", newline="\n")


def update_meta(vdir: Path, **fields) -> None:
    path = vdir / "meta.json"
    meta = json.loads(path.read_text(encoding="utf-8"))
    meta.update(fields)
    path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def expect_error(label: str, fn, *needles: str) -> None:
    try:
        fn()
    except ReportError as exc:
        missing = [n for n in needles if n not in str(exc)]
        if missing:
            raise SystemExit(f"FAIL {label}: error text lacks {missing}:\n{exc}")
        print(f"ok   {label}: refused -> {str(exc).splitlines()[0][:110]}")
        return
    raise SystemExit(f"FAIL {label}: no error raised")


# --------------------------------------------------------------------------- checks

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
BLOCK = {"address", "article", "aside", "blockquote", "div", "dl", "figure", "footer", "form", "h1", "h2", "h3",
         "h4", "h5", "h6", "header", "hr", "main", "nav", "ol", "p", "pre", "section", "table", "ul"}


class TagBalance(HTMLParser):
    """Every non-void tag closes in order; no block element inside <p> (a browser would split it)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, int]] = []
        self.errors: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in VOID:
            return
        if tag in BLOCK and any(t == "p" for t, _ in self.stack):
            self.errors.append(f"line {self.getpos()[0]}: <{tag}> inside <p>")
        self.stack.append((tag, self.getpos()[0]))

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        if not self.stack:
            self.errors.append(f"line {self.getpos()[0]}: </{tag}> with nothing open")
        elif self.stack[-1][0] != tag:
            self.errors.append(f"line {self.getpos()[0]}: </{tag}> closes <{self.stack[-1][0]}> "
                               f"opened at line {self.stack[-1][1]}")
            if any(t == tag for t, _ in self.stack):
                while self.stack and self.stack.pop()[0] != tag:
                    pass
        else:
            self.stack.pop()

    def finish(self) -> list[str]:
        self.close()
        return self.errors + [f"<{t}> opened at line {n} never closed" for t, n in self.stack]


def check_file(path: Path, *, artifact: bool = False, min_kb: int = 5, max_kb: int = 3000) -> list[str]:
    text = path.read_text(encoding="utf-8")
    parser = TagBalance()
    parser.feed(text)
    problems = parser.finish()
    if "{{" in text or "}}" in text:
        problems.append("placeholder braces left in the output")
    size_kb = path.stat().st_size / 1024
    if not min_kb <= size_kb <= max_kb:
        problems.append(f"size {size_kb:.0f} KB outside {min_kb}..{max_kb} KB")
    low = text.lower()
    if artifact:
        if not text.startswith("<title>"):
            problems.append("artifact.html must start with <title>")
        for shell in re.findall(r"<(!doctype|html|head|body)[\s>]", low):
            problems.append(f"artifact.html contains <{shell}>")
    elif path.name == "report.html":
        for need in ("<!doctype html>", '<html lang="ru">', "<style>", "fonts.googleapis.com"):
            if need not in low:
                problems.append(f"report.html lacks {need}")
    print(f"{'ok  ' if not problems else 'FAIL'} {path.relative_to(HERE)}  {size_kb:.1f} KB")
    for p in problems:
        print(f"       - {p}")
    return problems


def check_components(*paths: Path) -> list[str]:
    text = "".join(p.read_text(encoding="utf-8") for p in paths)
    need = ['class="wrap"', 'class="masthead"', 'class="eyebrow"', "<h1>", 'class="standfirst"', 'class="tiles"',
            'class="tile warn"', 'class="tile ad"', 'class="tile good"', 'class="k"', 'class="v"', 'class="n"',
            'class="answers"', 'class="ans"', 'class="q"', 'class="lede"', 'class="note"', 'class="calc"',
            "<figure>", 'class="figbox"', 'class="legend"', "<figcaption>", 'class="shot"', 'class="tag"',
            'class="frame"', 'class="shots2"', 'class="tablebox"', 'class="n ok"', 'class="n bad"',
            'class="total"', 'class="tnote"', 'class="cards"', 'class="card hot"', 'class="card adc"',
            'class="card okc"', 'class="cnt"', 'class="acts"', 'class="act"', 'class="why"', 'class="method"',
            "data:image/png;base64,", 'class="band"', 'class="refl"', 'class="refl alt"', 'class="ln s1"',
            'class="dot s1"', "mk s-good", "mk s-bad", "mk s-unk", "mk s-old", "mk s6", 'class="hit"',
            # the fixed skeleton
            'class="toc"', 'class="block" id="summary"', 'class="bn"', 'class="hyps"', 'class="hyp" id="h1"',
            'class="hid"', 'class="conf high"', 'class="conf mid"', 'class="conf low"', 'class="basis"',
            'class="test"', 'class="eff"', 'class="measure"', 'class="interp"', 'class="kpi"', 'class="drop"',
            'class="n est"', '<tr class="est">', "Retention D1", "Ушло, % от предыдущего",
            "Время шага, с", "№ в сессии", "Свернули за 20 с", "Не вернулись вовсе"]
    missing = [n for n in need if n not in text]
    names = ", ".join(p.parent.parent.name + "/" + p.parent.name for p in paths)
    print(f"{'ok  ' if not missing else 'FAIL'} every component and chart class present in {names}")
    return [f"missing {m}" for m in missing]


# --------------------------------------------------------------------------- main

def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    for generated in (ANALYTICS / "reports", ANALYTICS / "data"):
        if generated.exists():
            shutil.rmtree(generated)
    fake_db(ANALYTICS / "data" / "analytics.db")

    assert ch.fmt_num(1234.5, 1, "ru") == "1\N{NARROW NO-BREAK SPACE}234,5"
    assert ch.fmt_num(-1234.5, 1, "en") == "\N{MINUS SIGN}1,234.5"
    assert ch.fmt_money(0.13, 2, "ru") == "$0,13" and ch.fmt_pct(0.335, 0, "en", ratio=True) == "34%"
    print("ok   number formatting (ru / en)")

    expect_error("bad slug", lambda: new_version(ANALYTICS, "Bad Slug", "x"), "bad report slug")
    expect_error("bad kind", lambda: new_version(ANALYTICS, SLUG, "x", kind="essay"), "unknown report kind")

    title = "Пример 1.0.8 и 1.1.0, 01–20.09: полный разбор"
    v1 = new_version(ANALYTICS, SLUG, title, kind="full")
    scaffold = (v1 / "report.src.html").read_text(encoding="utf-8")
    if "Продуктовые метрики" not in scaffold or "__T_" in scaffold or 'id="hypotheses"' not in scaffold:
        raise SystemExit("FAIL the full scaffold is not localised or lacks its blocks")
    print("ok   full scaffold: blocks named in the report language")
    expect_error("scaffold without data window", lambda: build(ANALYTICS, SLUG), "data_window.since", "is empty")
    write_body(v1)
    write_md(v1, "v001", "20.09.2026")
    update_meta(v1, subtitle="Новички уходят на первой покупке в обучении, а закупка не окупается ни при какой ставке",
                question="Полный разбор игры за 01–20.09: что изменила 1.1.0, где теряем новичков, окупается ли закупка",
                data_window={"since": "2026-09-01", "until": "2026-09-20"},
                sources_used=["вымышленные данные", "скриншоты-заглушки"])
    r1 = build(ANALYTICS, SLUG)
    print(f"ok   built {r1.relative_to(HERE)}")
    expect_error("rebuild of a built version", lambda: build(ANALYTICS, SLUG, 1), "final", "--from v1")

    v2 = new_version(ANALYTICS, SLUG, title, from_version=1)
    good_src = (v2 / "report.src.html").read_text(encoding="utf-8")
    bad_src = good_src.replace("{{svg:assets/daily.svg}}", "{{svg:assets/missing.svg}} {{img:assets/x.bmp}}") \
        .replace("{{meta:question}}", "{{meta:nope}} {{foo:bar}} {{ stray")
    (v2 / "report.src.html").write_text(bad_src, encoding="utf-8", newline="\n")
    expect_error("unresolved placeholders", lambda: build(ANALYTICS, SLUG, 2),
                 "missing asset assets/missing.svg", "unsupported image type .bmp", "no field 'nope'",
                 "unknown placeholder", "stray")
    broken = (good_src.replace('<section class="block" id="countries">', '<section class="block" id="geo">')
              .replace('<a href="#revenue-ads">3.1</a>', '<a href="#nowhere">3.1</a>')
              .replace('<p class="eff"><b>Ожидаемый эффект:</b> потеря', '<p><b>Эффект:</b> потеря', 1)
              .replace('<p class="why">→ <a href="#h3">H3</a></p>', '<p class="why">→ раздел 3</p>')
              .replace('<span class="conf low">уверенность низкая</span>', '')
              .replace('<h3 id="summary-metrics">', '<h3 id="summary-answers">'))
    (v2 / "report.src.html").write_text(broken, encoding="utf-8", newline="\n")
    expect_error("structure of a full review", lambda: build(ANALYTICS, SLUG, 2),
                 "structure problem", "block #countries is missing", "link #nowhere points to no id",
                 "no link to a hypothesis", "no confidence mark", "no expected effect",
                 'id "summary-answers" is used 2 times')
    (v2 / "report.src.html").write_text(good_src.replace("</header>\n", CHANGES_V2, 1), encoding="utf-8",
                                         newline="\n")
    update_meta(v2, data_window={"since": "2026-09-01", "until": "2026-09-21"})
    write_md(v2, "v002", "21.09.2026")
    r2 = build(ANALYTICS, SLUG, 2)
    print(f"ok   built {r2.relative_to(HERE)} (from v001, kind kept: "
          f"{json.loads((v2 / 'meta.json').read_text(encoding='utf-8'))['kind']})")
    v3 = new_version(ANALYTICS, SLUG, "", from_version=2)
    print(f"ok   draft {v3.relative_to(HERE)} left unbuilt on purpose")

    q1 = new_version(ANALYTICS, QSLUG, "Пример: окупается ли закупка в США", kind="question")
    (q1 / "report.src.html").write_text(QUESTION_BODY, encoding="utf-8", newline="\n")
    write_assets(q1, ["revenue"])
    update_meta(q1, subtitle="Нет: игрок стоит втрое больше, чем приносит",
                question="Окупается ли закупка в США?", data_window={"since": "2026-09-17", "until": "2026-09-21"},
                sources_used=["вымышленные данные"])
    no_actions = QUESTION_BODY.replace('<section class="block" id="actions">', '<section class="block" id="todo">')
    (q1 / "report.src.html").write_text(no_actions, encoding="utf-8", newline="\n")
    expect_error("question report without recommendations", lambda: build(ANALYTICS, QSLUG),
                 "block #actions is missing")
    (q1 / "report.src.html").write_text(QUESTION_BODY, encoding="utf-8", newline="\n")
    rq = build(ANALYTICS, QSLUG)
    print(f"ok   built {rq.relative_to(HERE)} (question)")
    index = build_index(ANALYTICS)

    problems = []
    for vdir in (v1, v2, q1):
        problems += check_file(vdir / "report.html")
        problems += check_file(vdir / "artifact.html", artifact=True)
    problems += check_file(index, min_kb=1)
    problems += check_components(r2, rq)
    meta2 = json.loads((v2 / "meta.json").read_text(encoding="utf-8"))
    snap = (meta2.get("db_snapshot") or {})
    if (snap.get("tables", {}).get("events", {}).get("max_date") != "2026-09-21" or meta2.get("previous_version") != 1
            or meta2.get("kind") != "full" or snap.get("sample_rate") != 0.1):
        problems.append(f"meta.json of v002 is wrong: {meta2}")
    idx = index.read_text(encoding="utf-8")
    for need in ("sample/v002/report.html", "sample/v001/report.html", "sample/v002/report.md", "черновик", "Отчёты",
                 "sample-question/v001/report.html", "полный разбор", ">вопрос<"):
        if need not in idx:
            problems.append(f"index.html lacks {need}")
    with tempfile.TemporaryDirectory() as tmp:  # the same index in English
        en = Path(tmp) / "analytics"
        shutil.copytree(ANALYTICS / "reports", en / "reports")
        (en / "analytics.toml").write_text('[project]\nreport_language = "en"\n', encoding="utf-8")
        text = build_index(en).read_text(encoding="utf-8")
        if "Reports" not in text or ">draft<" not in text or "full review" not in text:
            problems.append("English index lacks its labels")
        q = new_version(en, "en-question", "Where do new players leave?")
        scaffold = (q / "report.src.html").read_text(encoding="utf-8")
        if "Hypotheses" not in scaffold or "Recommendations" not in scaffold or "__T_" in scaffold:
            problems.append("the English question scaffold is not localised")
    print("ok   index.html and scaffolds in ru and en" if not any("index" in p or "scaffold" in p for p in problems)
          else "FAIL index / scaffold")
    print(f"\n{'ALL CHECKS PASSED' if not problems else f'{len(problems)} PROBLEM(S)'}; open {index}")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
