"""SVG charts for reports.

Every chart function returns an SVG string (viewBox-based, width 100%) whose colours come
from the report theme through CSS classes, so one chart works in light and dark:

    marks    .s1 .. .s6  categorical, assign in this order and never cycle
             .s-old .s-unk  neutrals for "previous" and "unknown"
             .s-good .s-bad  semantic (revenue / loss)
    chrome   .grid (.zero) .ax .val .lab .ann .band .refl

Hovering a mark shows its <title>. Save a chart as assets/<name>.svg and reference it in
report.src.html as {{svg:assets/<name>.svg}}; opened on its own the file has no colours,
they live in theme.css. Put a legend above charts with two or more series: legend_html().

Numbers shown to people go through fmt_num / fmt_money / fmt_pct and follow the report
language (ru: 1 234,5 and 0,13 · en: 1,234.5 and 0.13). Coordinates are written by _f() and
never pass through a locale step: never run str.replace('.', ',') over an SVG string, it
corrupts every coordinate.

Common keyword arguments: unit ("" | "$" | "%" | any suffix such as "мин"), decimals (None =
automatic), lang ("ru" | "en"), fmt (callable value -> text, overrides unit), title (the
aria-label), x_label (axis note under the chart), width / height (viewBox units).
"""
from __future__ import annotations

import html
import math
from typing import Callable, Sequence

__all__ = ["fmt_num", "fmt_money", "fmt_pct", "bar", "grouped_bars", "stacked_bars", "hbars", "line",
           "ranked_bars", "legend_html", "annotate_band"]

NNBSP = "\u202f"  # narrow no-break space: Russian thousands separator
NBSP = "\u00a0"
MINUS = "\u2212"

_WORDS = {
    "ru": {"total": "всего", "mean": "среднее", "median": "медиана", "top": "первые {n} = {pct} суммы"},
    "en": {"total": "total", "mean": "mean", "median": "median", "top": "top {n} = {pct} of total"},
}


# --------------------------------------------------------------------------- number formatting

def fmt_num(value, decimals: int = 0, lang: str = "ru") -> str:
    """1234.5 -> '1 234,5' (ru, narrow no-break space) or '1,234.5' (en). None -> '—'."""
    if value is None:
        return "—"
    raw = float(value)
    # A small non-zero value must not print as zero ("$0,00" for $0.004 a player): add
    # decimals until its first significant digit shows, at most four more.
    while raw != 0 and round(raw, decimals) == 0 and decimals < 6:
        decimals += 1
    v = round(raw, decimals)
    s = f"{abs(v):,.{decimals}f}"
    if lang == "ru":
        s = s.translate({ord(","): NNBSP, ord("."): ","})
    return MINUS + s if v < 0 else s


def fmt_money(value, decimals: int = 2, lang: str = "ru", symbol: str = "$") -> str:
    """0.13 -> '$0,13' (ru) / '$0.13' (en); other symbols go after the number: '120 ₽'."""
    if value is None:
        return "—"
    sign = MINUS if float(value) < 0 and fmt_num(abs(float(value)), decimals, lang).strip("0,.") else ""
    s = fmt_num(abs(float(value)), decimals, lang)
    return f"{sign}{symbol}{s}" if symbol in ("$", "€", "£") else f"{sign}{s}{NBSP}{symbol}"


def fmt_pct(value, decimals: int = 0, lang: str = "ru", ratio: bool = False) -> str:
    """33 -> '33%'; with ratio=True the value is a fraction: 0.335 -> '34%'."""
    if value is None:
        return "—"
    return fmt_num(float(value) * (100 if ratio else 1), decimals, lang) + "%"


# --------------------------------------------------------------------------- shared helpers

def _esc(s) -> str:
    return html.escape(str(s), quote=True)


def _f(v: float) -> str:
    """Coordinate for SVG attributes: always a dot, one decimal at most."""
    s = f"{v:.1f}"
    s = s[:-2] if s.endswith(".0") else s
    return "0" if s == "-0" else s


def _tw(text: str, size: float = 11.0, mono: bool = True) -> float:
    """Estimated rendered width of text in viewBox units (good enough for layout)."""
    if mono:
        return len(text) * size * 0.6
    w = 0.0
    for ch in text:
        if ch in " .,:;·'!|ilI1()[]":
            w += 0.3
        elif ch.isupper() or ch in "mwMW%@":
            w += 0.7
        else:
            w += 0.58
    return w * size


def _wrap(text: str, max_w: float, size: float = 11.0, mono: bool = True) -> list[str]:
    lines, cur = [], ""
    for word in str(text or "").split():
        cand = f"{cur} {word}".strip()
        if cur and _tw(cand, size, mono) > max_w:
            lines.append(cur)
            cur = word
        else:
            cur = cand
    return lines + [cur] if cur else lines


def _clip(text: str, max_w: float, size: float = 13.0) -> str:
    if _tw(text, size, False) <= max_w:
        return text
    while text and _tw(text + "…", size, False) > max_w:
        text = text[:-1]
    return text.rstrip() + "…"


def _floats(values) -> list[float | None]:
    return [None if v is None else float(v) for v in values]


def _same_len(cats, values, what="values") -> None:
    if len(cats) != len(values):
        raise ValueError(f"{what}: {len(values)} values for {len(cats)} categories")


def _ticks(lo: float, hi: float, n: int = 5) -> tuple[list[float], float]:
    """Nice round ticks covering lo..hi, and their step."""
    if hi <= lo:
        hi = lo + 1
    span = hi - lo
    mag = 10 ** math.floor(math.log10(span / n))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if span / (m * mag) <= n + 1e-9)
    t0 = math.floor(lo / step + 1e-9) * step
    t1 = math.ceil(hi / step - 1e-9) * step
    return [round(t0 + i * step, 10) for i in range(int(round((t1 - t0) / step)) + 1)], step


def _tick_dec(step: float) -> int:
    d = max(0, -math.floor(math.log10(step) + 1e-9))
    scaled = step * 10 ** d
    return d + 1 if abs(scaled - round(scaled)) > 1e-6 else d


def _tick_texts(ticks, step: float, text) -> list[str]:
    """Tick labels with the decimals the step needs; zero is always plain (0, $0, 0%)."""
    d = _tick_dec(step)
    return [text(t, 0 if abs(t) < 1e-12 else d) for t in ticks]


def _auto_dec(values, unit: str) -> int:
    vals = [abs(v) for v in values if v is not None]
    if not vals or all(float(v).is_integer() for v in vals):
        return 0
    if unit == "$":
        return 2
    top = max(vals)
    return 0 if top >= 100 else 1 if top >= 1 else 2


def _formatter(unit: str, lang: str, fmt: Callable | None) -> Callable[[float, int], str]:
    if fmt is not None:
        return lambda v, d: fmt(v)
    if unit == "$":
        return lambda v, d: fmt_money(v, d, lang)
    if unit == "%":
        return lambda v, d: fmt_pct(v, d, lang)
    if unit:
        return lambda v, d: f"{fmt_num(v, d, lang)}{NBSP}{unit}"
    return lambda v, d: fmt_num(v, d, lang)


def _pick(highlight, cat, i, default: str) -> str:
    if not highlight:
        return default
    return highlight.get(cat, highlight.get(i, default))


def _show_values(mode, texts: Sequence[str], room: float) -> bool:
    if mode == "auto":
        return len(texts) <= 40 and max((_tw(t, 10.5) for t in texts), default=0) <= room
    return bool(mode)


def _fit_x(x: float, w: float, width: float, pad: float = 2) -> tuple[float, str]:
    """Centre a label on x unless it would leave the chart; then anchor it to the edge."""
    if x + w / 2 > width - pad:
        return width - pad, "end"
    if x - w / 2 < pad:
        return pad, "start"
    return x, "middle"


def _vbar(x: float, w: float, y0: float, y1: float, cls: str, r: float = 3.0) -> str:
    """Column from baseline y0 to data end y1; only the data end is rounded."""
    h = abs(y0 - y1)
    if h < 0.05 or w <= 0:
        return ""
    r = max(0.0, min(r, w / 2, h))
    if r < 0.3:
        return (f'<rect class="mk {cls}" x="{_f(x)}" y="{_f(min(y0, y1))}" width="{_f(w)}" '
                f'height="{_f(h)}"/>')
    up = y1 < y0
    e, s = (y1 + r, 1) if up else (y1 - r, 0)
    d = (f"M{_f(x)} {_f(y0)}V{_f(e)}A{_f(r)} {_f(r)} 0 0 {s} {_f(x + r)} {_f(y1)}"
         f"H{_f(x + w - r)}A{_f(r)} {_f(r)} 0 0 {s} {_f(x + w)} {_f(e)}V{_f(y0)}Z")
    return f'<path class="mk {cls}" d="{d}"/>'


def _hbar(x0: float, x1: float, y: float, h: float, cls: str, r: float = 3.0) -> str:
    """Bar from x0 to x1; only the right (data) end is rounded."""
    w = x1 - x0
    if w < 0.05:
        return ""
    r = max(0.0, min(r, h / 2, w))
    d = (f"M{_f(x0)} {_f(y)}H{_f(x1 - r)}A{_f(r)} {_f(r)} 0 0 1 {_f(x1)} {_f(y + r)}"
         f"V{_f(y + h - r)}A{_f(r)} {_f(r)} 0 0 1 {_f(x1 - r)} {_f(y + h)}H{_f(x0)}Z")
    return f'<path class="mk {cls}" d="{d}"/>'


def _open(width: float, height: float, title: str) -> list[str]:
    return [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {_f(width)} {_f(height)}" width="100%" '
            f'role="img" aria-label="{_esc(title or "chart")}">']


def _close(out: list[str]) -> str:
    out.append("</svg>")
    return "\n".join(s for s in out if s)


class _Frame:
    """Plot area with a vertical value axis and one slot per category along x."""

    def __init__(self, n, lo, hi, ticks, tick_text, note_lines, width, height, top, right):
        self.n, self.lo, self.hi, self.ticks, self.tick_text = max(n, 1), lo, hi, ticks, tick_text
        self.note_lines, self.W, self.H = note_lines, width, height
        self.L = _left(tick_text)
        self.T, self.R = top, width - right
        self.B = height - (42 + 15 * (len(note_lines) - 1) if note_lines else 24)
        self.pw, self.ph = self.R - self.L, self.B - self.T
        self.step = self.pw / self.n

    def y(self, v: float) -> float:
        return self.B - (v - self.lo) / (self.hi - self.lo) * self.ph

    @property
    def y0(self) -> float:
        return self.y(min(max(0.0, self.lo), self.hi))

    def cx(self, i: int) -> float:
        return self.L + (i + 0.5) * self.step


def _left(tick_text) -> float:
    return 4 + max((_tw(s) for s in tick_text), default=8) + 8


def _setup(cats, values, *, unit, lang, fmt, decimals, ymin, ymax, width, height, x_label, bands, right=14):
    """Scale, ticks and margins shared by the column and line charts. Returns (frame, value_text)."""
    vals = [v for v in values if v is not None]
    lo = min([0.0] + vals) if ymin is None else float(ymin)
    hi = max([0.0] + vals) if ymax is None else float(ymax)
    ticks, step = _ticks(lo, hi)
    lo = ticks[0] if ymin is None else lo
    hi = ticks[-1] if ymax is None else hi
    ticks = [t for t in ticks if lo - 1e-9 <= t <= hi + 1e-9]
    text = _formatter(unit, lang, fmt)
    tick_text = _tick_texts(ticks, step, text)
    notes = _wrap(x_label, width - _left(tick_text) - 4)
    top = 20 + (16 if any(_band(b)["label"] for b in bands or ()) else 0)
    frame = _Frame(len(cats), lo, hi, ticks, tick_text, notes, width, height, top, right)
    vd = decimals if decimals is not None else _auto_dec(vals, unit)
    return frame, (lambda v: text(v, vd))


def _grid(fr: _Frame, out: list[str]) -> None:
    for t, s in zip(fr.ticks, fr.tick_text):
        y = fr.y(t)
        cls = "grid zero" if abs(t) < 1e-12 else "grid"
        out.append(f'<line class="{cls}" x1="{_f(fr.L)}" x2="{_f(fr.R)}" y1="{_f(y)}" y2="{_f(y)}"/>')
        out.append(f'<text class="ax" x="{_f(fr.L - 8)}" y="{_f(y + 4)}" text-anchor="end">{_esc(s)}</text>')


def _xlabels(fr: _Frame, cats, out: list[str]) -> None:
    labels = [str(c) for c in cats]
    if not labels:
        return
    every = max(1, math.ceil((max(_tw(s) for s in labels) + 8) / fr.step))
    for i, s in enumerate(labels):
        if i % every == 0:
            x, anchor = _fit_x(fr.cx(i), _tw(s), fr.W)
            out.append(f'<text class="ax" x="{_f(x)}" y="{_f(fr.B + 16)}" text-anchor="{anchor}">{_esc(s)}</text>')


def _notes(fr: _Frame, out: list[str]) -> None:
    for k, text in enumerate(fr.note_lines):
        out.append(f'<text class="ax" x="{_f(fr.L)}" y="{_f(fr.B + 38 + 15 * k)}">{_esc(text)}</text>')


def _hit(fr: _Frame, i: int) -> str:
    return (f'<rect class="hit" x="{_f(fr.L + i * fr.step)}" y="{_f(fr.T)}" width="{_f(fr.step)}" '
            f'height="{_f(fr.ph)}"/>')


def _value(fr: _Frame, x: float, v: float, text: str) -> str:
    y = fr.y(v) - 5 if v >= 0 else fr.y(v) + 13
    return f'<text class="val" x="{_f(x)}" y="{_f(y)}" text-anchor="middle">{_esc(text)}</text>'


# --------------------------------------------------------------------------- bands and legends

def annotate_band(x_from, x_to=None, label: str = "") -> dict:
    """Shade categories x_from..x_to (inclusive; None = to the end) on a time chart, label above it.

    Pass the result in bands=[...] of bar, grouped_bars, stacked_bars or line. x_from / x_to are
    category values (or their indexes).
    """
    return {"from": x_from, "to": x_to, "label": label}


def _band(b) -> dict:
    return annotate_band(*b) if isinstance(b, (tuple, list)) else b


def _index(cats, value) -> int:
    if value in cats:
        return list(cats).index(value)
    if isinstance(value, int) and 0 <= value < len(cats):
        return value
    raise ValueError(f"{value!r} is not one of the chart's categories")


def _bands(fr: _Frame, cats, bands, out: list[str]) -> None:
    for b in map(_band, bands or ()):
        i0 = _index(cats, b["from"])
        i1 = len(cats) - 1 if b.get("to") is None else _index(cats, b["to"])
        i0, i1 = min(i0, i1), max(i0, i1)
        x0, x1 = fr.L + i0 * fr.step, fr.L + (i1 + 1) * fr.step
        out.append(f'<rect class="band" x="{_f(x0)}" y="{_f(fr.T)}" width="{_f(x1 - x0)}" height="{_f(fr.ph)}"/>')
        if b.get("label"):
            w = _tw(b["label"], 12, mono=False)
            x, anchor = (x0 + 6, "start") if x0 + 6 + w <= fr.W - 2 else (min(x1 - 6, fr.W - 2), "end")
            out.append(f'<text class="ann" x="{_f(x)}" y="{_f(fr.T - 8)}" text-anchor="{anchor}">'
                       f'{_esc(b["label"])}</text>')


def legend_html(items, line: bool = False) -> str:
    """[(label, css_class), ...] -> <div class="legend">, placed above the chart inside .figbox.

    A chart's series list [(label, css_class, values), ...] can be passed as is. A third item equal
    to "line" (or line=True for all) draws a short line key instead of a square swatch.
    """
    parts = []
    for item in items:
        label, cls = item[0], item[1]
        key = "sw lk" if line or (len(item) > 2 and item[2] == "line") else "sw"
        parts.append(f'<span><i class="{key} {_esc(cls)}"></i>{_esc(label)}</span>')
    return f'<div class="legend">{"".join(parts)}</div>'


# --------------------------------------------------------------------------- column charts

def bar(categories, values, *, cls: str = "s1", highlight: dict | None = None, unit: str = "",
        decimals: int | None = None, lang: str = "ru", title: str = "", x_label: str = "",
        ymin: float | None = None, ymax: float | None = None, bands=None, value_labels="auto",
        fmt: Callable | None = None, width: int = 720, height: int = 280) -> str:
    """One series of columns. highlight maps a category (or its index) to another class: {"15.09": "s2"}."""
    cats, vals = list(categories), _floats(values)
    _same_len(cats, vals)
    fr, vt = _setup(cats, vals, unit=unit, lang=lang, fmt=fmt, decimals=decimals, ymin=ymin, ymax=ymax,
                    width=width, height=height, x_label=x_label, bands=bands)
    out = _open(width, height, title)
    _bands(fr, cats, bands, out)
    _grid(fr, out)
    bw = min(28.0, fr.step * 0.72)
    texts = [vt(v) if v is not None else "—" for v in vals]
    show = _show_values(value_labels, texts, fr.step - 2)
    for i, (c, v) in enumerate(zip(cats, vals)):
        out.append(f'<g class="hv"><title>{_esc(c)}: {_esc(texts[i])}</title>{_hit(fr, i)}')
        if v is not None:
            out.append(_vbar(fr.cx(i) - bw / 2, bw, fr.y0, fr.y(v), _pick(highlight, c, i, cls)))
            out.append(_value(fr, fr.cx(i), v, texts[i]) if show else "")
        out.append("</g>")
    _xlabels(fr, cats, out)
    _notes(fr, out)
    return _close(out)


def grouped_bars(categories, series, *, unit: str = "", decimals: int | None = None, lang: str = "ru",
                 title: str = "", x_label: str = "", ymin: float | None = None, ymax: float | None = None,
                 bands=None, value_labels="auto", fmt: Callable | None = None,
                 width: int = 720, height: int = 280) -> str:
    """Side-by-side columns. series: [(label, css_class, values), ...], one bar per series per category."""
    cats = list(categories)
    ser = [(str(lab), c, _floats(vs)) for lab, c, vs in series]
    for lab, _, vs in ser:
        _same_len(cats, vs, lab)
    fr, vt = _setup(cats, [v for _, _, vs in ser for v in vs], unit=unit, lang=lang, fmt=fmt,
                    decimals=decimals, ymin=ymin, ymax=ymax, width=width, height=height,
                    x_label=x_label, bands=bands)
    out = _open(width, height, title)
    _bands(fr, cats, bands, out)
    _grid(fr, out)
    k = max(1, len(ser))
    group = min(fr.step * 0.8, k * 34 + (k - 1) * 2)
    bw = (group - 2 * (k - 1)) / k
    texts = [[vt(v) if v is not None else "—" for v in vs] for _, _, vs in ser]
    show = _show_values(value_labels, [t for row in texts for t in row], bw + 2)
    for i, c in enumerate(cats):
        gx = fr.cx(i) - group / 2
        for j, (lab, cls, vs) in enumerate(ser):
            x, v = gx + j * (bw + 2), vs[i]
            out.append(f'<g class="hv"><title>{_esc(c)} · {_esc(lab)}: {_esc(texts[j][i])}</title>'
                       f'<rect class="hit" x="{_f(x - 1)}" y="{_f(fr.T)}" width="{_f(bw + 2)}" height="{_f(fr.ph)}"/>')
            if v is not None:
                out.append(_vbar(x, bw, fr.y0, fr.y(v), cls))
                out.append(_value(fr, x + bw / 2, v, texts[j][i]) if show else "")
            out.append("</g>")
    _xlabels(fr, cats, out)
    _notes(fr, out)
    return _close(out)


def stacked_bars(categories, series, *, totals: bool = True, unit: str = "", decimals: int | None = None,
                 lang: str = "ru", title: str = "", x_label: str = "", ymax: float | None = None, bands=None,
                 fmt: Callable | None = None, width: int = 720, height: int = 300) -> str:
    """Stacked columns, bottom-up in series order: [(label, css_class, values), ...].

    Segments are separated by a 2 px surface gap; the total sits on top of each column and
    the hover title lists every segment.
    """
    cats = list(categories)
    ser = [(str(lab), c, [0.0 if v is None else v for v in _floats(vs)]) for lab, c, vs in series]
    for lab, _, vs in ser:
        _same_len(cats, vs, lab)
        if any(v < 0 for v in vs):
            raise ValueError(f"stacked_bars: negative value in series {lab!r}")
    sums = [sum(vs[i] for _, _, vs in ser) for i in range(len(cats))]
    fr, vt = _setup(cats, sums, unit=unit, lang=lang, fmt=fmt, decimals=decimals, ymin=0, ymax=ymax,
                    width=width, height=height, x_label=x_label, bands=bands)
    out = _open(width, height, title)
    _bands(fr, cats, bands, out)
    _grid(fr, out)
    bw = min(28.0, fr.step * 0.72)
    total_texts = [vt(s) for s in sums]
    show = totals and _show_values("auto", total_texts, fr.step - 2)
    word = _WORDS["ru" if lang == "ru" else "en"]["total"]
    for i, c in enumerate(cats):
        x = fr.cx(i) - bw / 2
        parts = "; ".join(f"{lab} {vt(vs[i])}" for lab, _, vs in ser)
        out.append(f'<g class="hv"><title>{_esc(c)} — {_esc(parts)} · {word} {_esc(total_texts[i])}</title>'
                   f'{_hit(fr, i)}')
        live = [j for j, (_, _, vs) in enumerate(ser) if vs[i] > 0]
        base = 0.0
        for j in live:
            _, cls, vs = ser[j]
            y0 = fr.y(base) - (2 if base > 0 else 0)
            out.append(_vbar(x, bw, y0, fr.y(base + vs[i]), cls, r=3 if j == live[-1] else 0))
            base += vs[i]
        if show and sums[i] > 0:
            out.append(_value(fr, fr.cx(i), sums[i], total_texts[i]))
        out.append("</g>")
    _xlabels(fr, cats, out)
    _notes(fr, out)
    return _close(out)


def ranked_bars(values, *, labels=None, highlight_top: int = 0, cls: str = "s1", highlight_cls: str = "s2",
                mean_line: bool = True, median_line: bool = False, top_share: bool = True, unit: str = "",
                decimals: int | None = None, lang: str = "ru", title: str = "", x_label: str = "",
                fmt: Callable | None = None, width: int = 720, height: int = 260) -> str:
    """One bar per item, sorted descending (players, devices, campaigns): shows concentration.

    highlight_top paints the first N bars with highlight_cls and (top_share) labels their share
    of the total; mean_line / median_line draw dashed reference lines labelled at the right edge.
    """
    vals = [float(v) for v in values]
    names = [str(s) for s in labels] if labels is not None else [""] * len(vals)
    _same_len(vals, names, "labels")
    order = sorted(range(len(vals)), key=lambda k: -vals[k])
    vals, names = [vals[k] for k in order], [names[k] for k in order]
    n = len(vals)
    words = _WORDS["ru" if lang == "ru" else "en"]
    fr, vt = _setup(list(range(n)), vals, unit=unit, lang=lang, fmt=fmt, decimals=decimals, ymin=None,
                    ymax=None, width=width, height=height, x_label=x_label, bands=None)
    out = _open(width, height, title)
    _grid(fr, out)
    bw = fr.step * 0.72 if fr.step >= 6 else max(fr.step - 0.6, 0.4)
    for i, v in enumerate(vals):
        tip = f"#{i + 1}{' ' + names[i] if names[i] else ''}: {vt(v)}"
        out.append(f'<g class="hv"><title>{_esc(tip)}</title>{_hit(fr, i)}'
                   f'{_vbar(fr.cx(i) - bw / 2, bw, fr.y0, fr.y(v), highlight_cls if i < highlight_top else cls)}</g>')
    refs = []
    if mean_line and n:
        refs.append(("refl", sum(vals) / n, words["mean"]))
    if median_line and n:
        mid = n // 2
        refs.append(("refl alt", vals[mid] if n % 2 else (vals[mid - 1] + vals[mid]) / 2, words["median"]))
    ys = [fr.y(v) for _, v, _ in refs]
    close = len(ys) == 2 and abs(ys[0] - ys[1]) < 16  # labels side by side above the higher line
    label_x = fr.R - 2
    for k, (rcls, v, word) in enumerate(refs):
        text = f"{word} {vt(v)}"
        out.append(f'<line class="{rcls}" x1="{_f(fr.L)}" x2="{_f(fr.R)}" y1="{_f(ys[k])}" y2="{_f(ys[k])}"/>')
        out.append(f'<text class="ann" x="{_f(label_x)}" y="{_f((min(ys) if close else ys[k]) - 6)}" '
                   f'text-anchor="end">{_esc(text)}</text>')
        label_x -= _tw(text, 12, False) + 18 if close else 0
    total = sum(vals)
    if top_share and 0 < highlight_top < n and total > 0:
        text = words["top"].format(n=highlight_top, pct=fmt_pct(sum(vals[:highlight_top]) / total * 100, 0, lang))
        y = max(fr.T + 12, fr.y(vals[highlight_top]) - 10)
        out.append(f'<text class="ann" x="{_f(fr.L + highlight_top * fr.step + 6)}" y="{_f(y)}">{_esc(text)}</text>')
    steps = (5, 10, 20, 50, 100, 200, 500, 1000, 10 ** 9) if n > 12 else (1, 2, 5, 10)
    every = next(m for m in steps if m * fr.step >= 26)
    for i in sorted({0, *range(every - 1, n, every)}):
        x, anchor = _fit_x(fr.cx(i), _tw(str(i + 1)), fr.W)
        out.append(f'<text class="ax" x="{_f(x)}" y="{_f(fr.B + 16)}" text-anchor="{anchor}">{i + 1}</text>')
    _notes(fr, out)
    return _close(out)


# --------------------------------------------------------------------------- bars and lines

def hbars(labels, values, *, cls: str = "s1", highlight: dict | None = None, unit: str = "",
          decimals: int | None = None, lang: str = "ru", title: str = "", x_label: str = "",
          xmax: float | None = None, value_labels: bool = True, fmt: Callable | None = None,
          width: int = 720, row_height: int = 34) -> str:
    """Horizontal bars for long category names: names on the left, the value at the bar end."""
    names, vals = [str(s) for s in labels], _floats(values)
    _same_len(names, vals)
    if any(v is not None and v < 0 for v in vals):
        raise ValueError("hbars draws non-negative values")
    text = _formatter(unit, lang, fmt)
    vd = decimals if decimals is not None else _auto_dec(vals, unit)
    texts = [text(v, vd) if v is not None else "—" for v in vals]
    ticks, step = _ticks(0.0, max([0.0] + [v for v in vals if v is not None]) if xmax is None else float(xmax))
    hi = ticks[-1] if xmax is None else float(xmax)
    ticks = [t for t in ticks if t <= hi + 1e-9]
    tick_text = _tick_texts(ticks, step, text)
    shown = [_clip(s, width * 0.42 - 12) for s in names]
    L = 12 + max((_tw(s, 13, False) for s in shown), default=0)
    R = width - 8 - max(max((_tw(t, 10.5) for t in texts), default=0) + 6 if value_labels else 0,
                        _tw(tick_text[-1]) / 2)
    T, axis_y = 6, 6 + row_height * len(names)
    notes = _wrap(x_label, width - L - 4)
    height = axis_y + 24 + (18 + 15 * (len(notes) - 1) if notes else 0)
    x = lambda v: L + v / hi * (R - L)
    out = _open(width, height, title)
    for t, s in zip(ticks, tick_text):
        cls_g = "grid zero" if t == 0 else "grid"
        out.append(f'<line class="{cls_g}" x1="{_f(x(t))}" x2="{_f(x(t))}" y1="{_f(T)}" y2="{_f(axis_y)}"/>')
        tx, anchor = _fit_x(x(t), _tw(s), width)
        out.append(f'<text class="ax" x="{_f(tx)}" y="{_f(axis_y + 16)}" text-anchor="{anchor}">{_esc(s)}</text>')
    bh = min(22.0, row_height * 0.62)
    for i, (name, v) in enumerate(zip(names, vals)):
        y = T + i * row_height + (row_height - bh) / 2
        out.append(f'<g class="hv"><title>{_esc(name)}: {_esc(texts[i])}</title>'
                   f'<rect class="hit" x="0" y="{_f(T + i * row_height)}" width="{_f(width)}" height="{_f(row_height)}"/>'
                   f'<text class="lab" x="{_f(L - 10)}" y="{_f(y + bh / 2 + 4.5)}" text-anchor="end">{_esc(shown[i])}</text>')
        if v is not None:
            out.append(_hbar(L, x(min(v, hi)), y, bh, _pick(highlight, name, i, cls)))
            if value_labels:
                out.append(f'<text class="val" x="{_f(x(min(v, hi)) + 6)}" y="{_f(y + bh / 2 + 4)}">{_esc(texts[i])}</text>')
        out.append("</g>")
    for k, line_text in enumerate(notes):
        out.append(f'<text class="ax" x="{_f(L)}" y="{_f(axis_y + 38 + 15 * k)}">{_esc(line_text)}</text>')
    return _close(out)


def line(x, series, *, markers="auto", end_labels: bool = True, unit: str = "", decimals: int | None = None,
         lang: str = "ru", title: str = "", x_label: str = "", ymin: float | None = None,
         ymax: float | None = None, bands=None, annotations=None, fmt: Callable | None = None,
         width: int = 720, height: int = 280) -> str:
    """Lines over categories x. series: [(label, css_class, values), ...]; None breaks a line.

    markers: True / False / "auto" (up to 31 points). end_labels puts the last value at the
    right end of each line (a colliding one is left to the tooltip). annotations: [(x_value,
    text), ...] draws a dashed vertical marker with a label; bands: [annotate_band(...)].
    """
    cats = list(x)
    ser = [(str(lab), c, _floats(vs)) for lab, c, vs in series]
    for lab, _, vs in ser:
        _same_len(cats, vs, lab)
    allv = [v for _, _, vs in ser for v in vs if v is not None]
    text = _formatter(unit, lang, fmt)
    vd = decimals if decimals is not None else _auto_dec(allv, unit)
    last = len(cats) - 1  # only lines that reach the right edge get an end label; the rest use the tooltip
    ends = [(v_end, text(v_end, vd)) for _, _, vs in ser if end_labels and cats and (v_end := vs[last]) is not None]
    right = 14 + (max((_tw(t, 10.5) for _, t in ends), default=0) + 8 if ends else 0)
    fr, vt = _setup(cats, allv, unit=unit, lang=lang, fmt=fmt, decimals=vd,
                    ymin=ymin if ymin is not None else (0 if min(allv, default=0) >= 0 else None),
                    ymax=ymax, width=width, height=height, x_label=x_label, bands=bands, right=right)
    out = _open(width, height, title)
    _bands(fr, cats, bands, out)
    _grid(fr, out)
    for xv, label in annotations or ():
        ax = fr.cx(_index(cats, xv))
        out.append(f'<line class="refl" x1="{_f(ax)}" x2="{_f(ax)}" y1="{_f(fr.T)}" y2="{_f(fr.B)}"/>')
        right_side = ax + 5 + _tw(label, 12, False) <= fr.R
        out.append(f'<text class="ann" x="{_f(ax + 5 if right_side else ax - 5)}" y="{_f(fr.T + 12)}" '
                   f'text-anchor="{"start" if right_side else "end"}">{_esc(label)}</text>')
    for _, cls, vs in ser:
        d, pen = [], "M"
        for i, v in enumerate(vs):
            if v is None:
                pen = "M"
                continue
            d.append(f"{pen}{_f(fr.cx(i))} {_f(fr.y(v))}")
            pen = "L"
        out.append(f'<path class="ln {cls}" d="{"".join(d)}"/>' if d else "")
    dots = len(cats) <= 31 if markers == "auto" else bool(markers)
    for i, c in enumerate(cats):
        parts = "; ".join(f"{lab} {vt(vs[i])}" for lab, _, vs in ser if vs[i] is not None)
        out.append(f'<g class="hv"><title>{_esc(c)} — {_esc(parts or "—")}</title>{_hit(fr, i)}')
        for _, cls, vs in ser:
            if dots and vs[i] is not None:
                out.append(f'<circle class="dot {cls}" cx="{_f(fr.cx(i))}" cy="{_f(fr.y(vs[i]))}" r="4"/>')
        out.append("</g>")
    placed: list[float] = []
    for v, t in sorted(ends, key=lambda e: -e[0]):
        y = fr.y(v) + 4
        if all(abs(y - p) >= 12 for p in placed):  # a colliding label is left to the tooltip
            placed.append(y)
            out.append(f'<text class="val" x="{_f(fr.cx(last) + 8)}" y="{_f(y)}">{_esc(t)}</text>')
    _xlabels(fr, cats, out)
    _notes(fr, out)
    return _close(out)
