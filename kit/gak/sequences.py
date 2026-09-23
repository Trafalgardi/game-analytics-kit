"""Two more standard tables of a full review, read from event sequences.

DESIGN.md section 5, "Standard tables". Both take the same population as metrics.py
(`--players`, cohort by first event in since..until) and work on the device's ordered events.

    ordinals  core actions by their number within a session: how many devices do an action a
              1st, 2nd, ... Nth time in one session, and how far into the session (median and
              mean seconds since the session's first event, or the action's own `sec`).
    leaving   what happens right after an event (lost an item, got hit, an ad started): the
              share of devices that background the app within the window (a pause event), that
              stop acting within it, that never come back, and that return after the pause.

Actions and triggers are event names (`--events a,b`) or a project relation with the columns
the command needs (`--actions` device_id, session_id, ts, label [, sec]; `--triggers`
device_id, ts, label), so a parameter-level event or the project's own session unit (a launch
instead of an SDK session) works too. Pause and resume moments are event names too, or a
relation of device_id, ts when the game sends one event with a flag (focus True/False).
"""

from __future__ import annotations

import bisect
import html
import io
import json
import sqlite3
import statistics
from dataclasses import dataclass

from . import GakError, query
from .metrics import (IDENT_RE, SELECT_RE, Population, _k, _relation, _share, _window, load_population,
                      source_label)

MAX_N = 15
WINDOW = 20


def _names(spec: str | None) -> list[str]:
    return [n.strip() for n in (spec or "").split(",") if n.strip()]


def _placeholders(names: list[str]) -> str:
    return ", ".join("?" for _ in names)


PAUSE, RESUME = "__pause__", "__resume__"


def _moments(conn: sqlite3.Connection, spec: str | None, what: str) -> tuple[set[str], list[tuple]]:
    """--pause / --resume: event names, or a view / SELECT of device_id, ts (flag-level events)."""
    if not spec:
        return set(), []
    text = spec.strip()
    known = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'view')")}
    if SELECT_RE.match(text) or (IDENT_RE.match(text) and text in known):
        sql = _relation(conn, text, "device_id, ts", what)
        rows = conn.execute(f"SELECT m.device_id, CAST(m.ts AS INTEGER) FROM ({sql}) m "
                            "JOIN temp.gak_pop p ON p.device_id = m.device_id WHERE m.ts IS NOT NULL").fetchall()
        return set(), rows
    return set(_names(text)), []


# --------------------------------------------------------------------------- #
# ordinals
# --------------------------------------------------------------------------- #

@dataclass
class OrdinalRow:
    label: str
    n: int
    devices: int
    occurrences: int
    pct: float                 # devices as % of the cohort
    sec_median: float | None
    sec_mean: float | None


@dataclass
class Ordinals:
    rows: list[OrdinalRow]
    population: Population
    source: str
    max_n: int
    own_clock: bool            # seconds come from the project's `sec` column
    notes: list[str]


def ordinals(conn: sqlite3.Connection, *, events: str | None = None, actions: str | None = None,
             players: str | None = None, since: str | None = None, until: str | None = None,
             max_n: int = MAX_N) -> Ordinals:
    if not events and not actions:
        raise GakError("give --events name1,name2 or --actions <view or SELECT>")
    pop = load_population(conn, players=players, since=since, until=until)
    notes: list[str] = []
    rows: list[tuple] = []
    if actions:
        try:
            sql, has_sec = _relation(conn, actions, "device_id, session_id, ts, label, sec", "--actions"), True
        except GakError:
            sql, has_sec = _relation(conn, actions, "device_id, session_id, ts, label", "--actions"), False
        rows = conn.execute(f"SELECT a.device_id, a.session_id, CAST(a.ts AS INTEGER), 0, a.label"
                            f"{', a.sec' if has_sec else ''} FROM ({sql}) a "
                            "JOIN temp.gak_pop p ON p.device_id = a.device_id WHERE a.ts IS NOT NULL").fetchall()
        source = actions
    else:
        names = _names(events)
        has_sec = False
        rows = conn.execute(
            "SELECT e.appmetrica_device_id, e.session_id, e.event_timestamp, e.id, e.event_name "
            "FROM events e JOIN temp.gak_pop p ON p.device_id = e.appmetrica_device_id "
            f"WHERE e.event_name IN ({_placeholders(names)}) AND e.event_timestamp IS NOT NULL", names).fetchall()
        source = ", ".join(names)
        found = {r[4] for r in rows}
        missing = [n for n in names if n not in found]
        if missing:
            notes.append(f"no rows for these devices: {', '.join(missing)}")
    starts: dict[tuple, int] = {}
    if not has_sec:  # seconds into the session: from the session's first event of any kind
        for device, sid, first in conn.execute(
                "SELECT e.appmetrica_device_id, e.session_id, MIN(e.event_timestamp) FROM events e "
                "JOIN temp.gak_pop p ON p.device_id = e.appmetrica_device_id GROUP BY 1, 2"):
            starts[(device, str(sid))] = first
    ordered: dict[tuple, list[tuple]] = {}
    for row in rows:
        ordered.setdefault((row[0], str(row[1]), str(row[4])), []).append(row)
    first_in_rows: dict[tuple, int] = {}
    for (device, sid, _), items in ordered.items():
        low = min(int(r[2]) for r in items if r[2] is not None)
        first_in_rows[(device, sid)] = min(first_in_rows.get((device, sid), low), low)
    per: dict[tuple, dict] = {}
    for (device, sid, label), items in ordered.items():
        items.sort(key=lambda r: (r[2], r[3]))
        start = starts.get((device, sid), first_in_rows.get((device, sid)))
        for n, row in enumerate(items[:max_n], 1):
            slot = per.setdefault((label, n), {"devices": set(), "occ": 0, "sec": []})
            slot["devices"].add(device)
            slot["occ"] += 1
            sec = row[5] if has_sec else (int(row[2]) - start if start is not None else None)
            if sec is not None:
                try:
                    slot["sec"].append(float(str(sec).replace(",", ".")))
                except ValueError:
                    pass
    total = len(pop.devices)
    out = [OrdinalRow(label, n, len(v["devices"]), v["occ"], 100.0 * len(v["devices"]) / total,
                      statistics.median(v["sec"]) if v["sec"] else None,
                      statistics.fmean(v["sec"]) if v["sec"] else None)
           for (label, n), v in sorted(per.items())]
    if not has_sec:
        notes.append("seconds = since the first event of the session (wall clock, includes backgrounded "
                     "time); give --actions with a `sec` column for the game's own play-time counter")
    return Ordinals(out, pop, source, max_n, has_sec, notes)


# --------------------------------------------------------------------------- #
# leaving
# --------------------------------------------------------------------------- #

@dataclass
class LeavingRow:
    label: str
    occurrences: int
    devices: int
    paused: int | None         # devices that backgrounded within the window (pause event)
    resumed: int | None        # of those, devices back within the window after the pause
    stopped: int               # devices with no other event within the window
    never_back: int            # devices whose trigger was followed by no event at all


@dataclass
class Leaving:
    rows: list[LeavingRow]
    population: Population
    source: str
    window: int
    pause_events: list[str]
    resume_events: list[str]
    notes: list[str]


def leaving(conn: sqlite3.Connection, *, events: str | None = None, triggers: str | None = None,
            pause_events: str | None = None, resume_events: str | None = None, ignore: str | None = None,
            window: int = WINDOW, players: str | None = None, since: str | None = None,
            until: str | None = None) -> Leaving:
    if not events and not triggers:
        raise GakError("give --events name1,name2 or --triggers <view or SELECT>")
    pop = load_population(conn, players=players, since=since, until=until)
    pauses, pause_rows = _moments(conn, pause_events, "--pause")
    resumes, resume_rows = _moments(conn, resume_events, "--resume")
    ignored = set(_names(ignore))  # events that are not the player acting (heartbeats, focus flags)
    stream: dict[str, list[tuple]] = {}  # device -> [(ts, id, name)]
    for device, ts, ident, name in conn.execute(
            "SELECT e.appmetrica_device_id, e.event_timestamp, e.id, e.event_name FROM events e "
            "JOIN temp.gak_pop p ON p.device_id = e.appmetrica_device_id "
            "WHERE e.event_timestamp IS NOT NULL ORDER BY 1, 2, 3"):
        stream.setdefault(device, []).append((int(ts), int(ident), name))
    for rows_, name in ((pause_rows, PAUSE), (resume_rows, RESUME)):
        if rows_:
            (pauses if name == PAUSE else resumes).add(name)
            for device, ts in rows_:
                stream.setdefault(device, []).append((int(ts), 2 ** 62, name))  # after events of that second
    for items in stream.values():
        items.sort()
    notes: list[str] = []
    if triggers:
        sql = _relation(conn, triggers, "device_id, ts, label", "--triggers")
        found = [(d, int(ts), None, str(label)) for d, ts, label in conn.execute(
            f"SELECT t.device_id, t.ts, t.label FROM ({sql}) t JOIN temp.gak_pop p ON p.device_id = t.device_id "
            "WHERE t.ts IS NOT NULL")]
        source = triggers
    else:
        names = set(_names(events))
        found = [(d, ts, ident, name) for d, items in stream.items() for ts, ident, name in items if name in names]
        source = ", ".join(_names(events))
        missing = names - {f[3] for f in found}
        if missing:
            notes.append(f"no rows for these devices: {', '.join(sorted(missing))}")
    if pauses and not any(name in pauses for items in stream.values() for _, _, name in items):
        notes.append(f"pause events {', '.join(sorted(pauses))} never occur for these devices")
    keys = {d: [(ts, ident) for ts, ident, _ in items] for d, items in stream.items()}
    per: dict[str, dict] = {}
    for device, ts, ident, label in found:
        items, index = stream.get(device, []), keys.get(device, [])
        pos = bisect.bisect_right(index, (ts, ident if ident is not None else 2 ** 62))
        after = items[pos:]
        slot = per.setdefault(label, {"occ": 0, "devices": set(), "paused": set(), "resumed": set(),
                                      "stopped": set(), "never": set()})
        slot["occ"] += 1
        slot["devices"].add(device)
        if not after:
            slot["never"].add(device)
        near = [e for e in after if e[0] - ts <= window]
        acting = [e for e in near if e[2] not in pauses and e[2] not in resumes and e[2] not in ignored
                  and e[2] != label]
        if not acting:
            slot["stopped"].add(device)
        pause = next((e for e in near if e[2] in pauses), None)
        if pause is not None:
            slot["paused"].add(device)
            back = next((e for e in items[bisect.bisect_right(index, (pause[0], pause[1])):]
                         if e[0] - pause[0] <= window
                         and (e[2] in resumes if resumes else e[2] not in pauses and e[2] not in ignored)),
                        None)
            if back is not None:
                slot["resumed"].add(device)
    rows = [LeavingRow(label, v["occ"], len(v["devices"]), len(v["paused"]) if pauses else None,
                       len(v["resumed"]) if pauses else None, len(v["stopped"]), len(v["never"]))
            for label, v in sorted(per.items(), key=lambda kv: -len(kv[1]["devices"]))]
    shown = lambda spec, names: [spec.strip()] if spec and names & {PAUSE, RESUME} else sorted(names)  # noqa: E731
    return Leaving(rows, pop, source, window, shown(pause_events, pauses), shown(resume_events, resumes), notes)


# --------------------------------------------------------------------------- #
# rendering
# --------------------------------------------------------------------------- #

TEXT = {
    "ru": {
        "n": "№ в сессии", "devices": "Устройств", "pct": "% когорты", "occ": "Событий",
        "median": "Медиана, мин:с", "mean": "Среднее, мин:с",
        "ord_note": ("Когорта — {n} устройств с первым событием {window} ({source}). N-е действие — "
                     "N-й раз в одной сессии; время — {clock}."),
        "clock_start": "от первого события сессии (часы, включая свёрнутое время)",
        "clock_sec": "из поля sec проекта",
        "trigger": "Событие", "had": "Было у устройств", "paused": "Свернули за {w} с",
        "resumed": "Вернулись за {w} с", "stopped": "Больше ничего за {w} с", "never": "Не вернулись вовсе",
        "leave_note": ("Когорта — {n} устройств с первым событием {window} ({source}). Доли — от устройств, "
                       "у которых событие было хотя бы раз; «свернули» — событие сворачивания ({pause}) в течение {w} с, "
                       "«вернулись» — от свернувших; «больше ничего» — ни одного другого события за {w} с; "
                       "«не вернулись вовсе» — после события у устройства нет ни одного события."),
        "no_pause": "не задано",
        "sample": " Выборка {pct} устройств: число устройств — по выборке (оценка — × {k}), доли не пересчитываются.",
    },
    "en": {
        "n": "N in session", "devices": "Devices", "pct": "% of cohort", "occ": "Events",
        "median": "Median, m:ss", "mean": "Mean, m:ss",
        "ord_note": ("Cohort: {n} devices whose first event is in {window} ({source}). The Nth action is "
                     "the Nth time within one session; time is {clock}."),
        "clock_start": "since the session's first event (wall clock, includes backgrounded time)",
        "clock_sec": "the project's sec field",
        "trigger": "Event", "had": "Devices with it", "paused": "Backgrounded within {w} s",
        "resumed": "Back within {w} s", "stopped": "Nothing else within {w} s", "never": "Never came back",
        "leave_note": ("Cohort: {n} devices whose first event is in {window} ({source}). Shares are of "
                       "devices that had the event at least once; backgrounded = a pause event ({pause}) within "
                       "{w} s, back = of those backgrounded; nothing else = no other event within {w} s; never "
                       "came back = no event at all after it."),
        "no_pause": "not given",
        "sample": " A {pct} device sample: device counts are the sample (× {k} for an estimate); shares stand as they are.",
    },
}


def _tx(lang: str) -> dict:
    return TEXT["ru" if lang == "ru" else "en"]


def _clock(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    s = int(round(seconds))
    return f"{s // 60}:{s % 60:02d}"


def _sample_note(pop: Population, lang: str) -> str:
    if pop.rate >= 1:
        return ""
    return _tx(lang)["sample"].format(pct=_share(pop.rate, lang), k=_k(pop.rate))


def render_ordinals(result: Ordinals, fmt: str, lang: str) -> str:
    pop = result.population
    if fmt == "json":
        return json.dumps({"population": pop.source, "window": list(pop.window), "sample_rate": pop.rate,
                           "source": result.source, "notes": result.notes,
                           "rows": [r.__dict__ for r in result.rows]}, ensure_ascii=False, indent=1)
    if fmt == "html":
        from .report import charts
        t = _tx(lang)
        parts = []
        for label in dict.fromkeys(r.label for r in result.rows):
            body = "\n".join(
                f'    <tr><td>{r.n}</td><td class="n">{charts.fmt_num(r.devices, 0, lang)}</td>'
                f'<td class="n">{charts.fmt_num(r.pct, 1, lang)}%</td><td class="n">{_clock(r.sec_median)}</td>'
                f'<td class="n">{_clock(r.sec_mean)}</td></tr>'
                for r in result.rows if r.label == label)
            parts.append(f'<div class="tablebox">\n<table class="drop ord">\n  <thead><tr><th>{html.escape(label)} · '
                         f'{t["n"]}</th><th class="n">{t["devices"]}</th><th class="n">{t["pct"]}</th>'
                         f'<th class="n">{t["median"]}</th><th class="n">{t["mean"]}</th></tr></thead>\n'
                         f"  <tbody>\n{body}\n  </tbody>\n</table>\n</div>\n")
        since, until = pop.window
        clock = t["clock_sec"] if result.own_clock else t["clock_start"]
        note = t["ord_note"].format(n=charts.fmt_num(len(pop.devices), 0, lang), window=_window(since, until, lang),
                                    source=html.escape(source_label(pop.source, lang)),
                                    clock=clock)
        return "".join(parts) + f'<p class="tnote">{note}{_sample_note(pop, lang)}</p>\n'
    table = query.Result(["action", "n", "devices", "pct_of_cohort", "events", "median_sec", "mean_sec"],
                         [[r.label, r.n, r.devices, round(r.pct, 1), r.occurrences,
                           None if r.sec_median is None else round(r.sec_median, 1),
                           None if r.sec_mean is None else round(r.sec_mean, 1)] for r in result.rows])
    buffer = io.StringIO()
    query.render(table, fmt, buffer)
    if fmt == "table":
        since, until = pop.window
        buffer.write(f"cohort: {len(pop.devices):,} device(s) with a first event in {since}..{until} from "
                     f"{pop.source}; actions: {result.source}; N counted within one session, up to {result.max_n}\n")
        for note in result.notes:
            buffer.write(f"note: {note}\n")
    return buffer.getvalue()


def render_leaving(result: Leaving, fmt: str, lang: str) -> str:
    pop = result.population
    if fmt == "json":
        return json.dumps({"population": pop.source, "window": list(pop.window), "sample_rate": pop.rate,
                           "source": result.source, "window_sec": result.window, "pause_events": result.pause_events,
                           "resume_events": result.resume_events, "notes": result.notes,
                           "rows": [r.__dict__ for r in result.rows]}, ensure_ascii=False, indent=1)

    def pct(part: int | None, whole: int) -> float | None:
        return None if part is None or not whole else 100.0 * part / whole

    if fmt == "html":
        from .report import charts
        t, w = _tx(lang), result.window

        def cell(part: int | None, whole: int) -> str:
            share = pct(part, whole)
            if share is None:
                return '<td class="n">—</td>'
            return (f'<td class="n">{charts.fmt_num(share, 1, lang)}%'
                    f'<small>{charts.fmt_num(part, 0, lang)} {t["devices"].lower()}</small></td>')

        body = "\n".join(
            f"    <tr><td>{html.escape(r.label)}</td><td class=\"n\">{charts.fmt_num(r.devices, 0, lang)}</td>"
            + (cell(r.paused, r.devices) + cell(r.resumed, r.paused or 0) if result.pause_events else "")
            + cell(r.stopped, r.devices) + cell(r.never_back, r.devices) + "</tr>"
            for r in result.rows)
        heads = [t["trigger"], t["had"]] + ([t["paused"].format(w=w), t["resumed"].format(w=w)]
                                            if result.pause_events else []) \
            + [t["stopped"].format(w=w), t["never"]]
        head = f"<th>{heads[0]}</th>" + "".join(f'<th class="n">{h}</th>' for h in heads[1:])
        since, until = pop.window
        note = t["leave_note"].format(n=charts.fmt_num(len(pop.devices), 0, lang), window=_window(since, until, lang),
                                      source=html.escape(source_label(pop.source, lang)),
                                      w=w, pause=html.escape(source_label(", ".join(result.pause_events), lang))
                                      or t["no_pause"])
        return ('<div class="tablebox">\n<table class="drop">\n'
                f"  <thead><tr>{head}</tr></thead>\n  <tbody>\n{body}\n  </tbody>\n</table>\n</div>\n"
                f'<p class="tnote">{note}{_sample_note(pop, lang)}</p>\n')
    heads = ["event", "occurrences", "devices"] + (["paused_pct", "resumed_pct_of_paused"] if result.pause_events
                                                   else []) + ["stopped_pct", "never_back_pct"]
    table = query.Result(heads, [
        [r.label, r.occurrences, r.devices]
        + ([_round(pct(r.paused, r.devices)), _round(pct(r.resumed, r.paused or 0))] if result.pause_events else [])
        + [_round(pct(r.stopped, r.devices)), _round(pct(r.never_back, r.devices))]
        for r in result.rows])
    buffer = io.StringIO()
    query.render(table, fmt, buffer)
    if fmt == "table":
        since, until = pop.window
        buffer.write(f"cohort: {len(pop.devices):,} device(s) with a first event in {since}..{until} from "
                     f"{pop.source}; window {result.window} s; pause events: "
                     f"{', '.join(result.pause_events) or 'none (only stopped / never back)'}\n")
        for note in result.notes:
            buffer.write(f"note: {note}\n")
    return buffer.getvalue()


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 1)
