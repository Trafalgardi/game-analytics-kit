"""Standard tables of a full review: key metrics per cohort group, and drop-off.

DESIGN.md section 5, "Standard tables". Both read the core tables (events,
ad_revenue_events, revenue_events, installations) through a read-only connection, plus two
optional project inputs, each a view / table name or a SELECT statement:

    players  rows with device_id: the population. Default: v_players when the project model
             has it (developer devices are excluded there), otherwise every device.
    steps    rows device_id, step_no, step_name: ordered steps such as loading and FTUE.

Definitions match the analytics-data-model metrics reference: the device is the unit, a
cohort is grouped by the device's first event (v_device_first_seen), DN counts only devices
whose day N is complete, active time is the sum of gaps between consecutive events of one
session with each gap capped. A sampled database keeps rates as they are and gets an
estimate (sample / rate) next to every absolute count.
"""

from __future__ import annotations

import html
import io
import json
import re
import sqlite3
import statistics
from dataclasses import dataclass, field
from datetime import date

from . import GakError, query, store

DEFAULT_CAP = 600
RETENTION_DAYS = (1, 3, 7)
IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?$")
SELECT_RE = re.compile(r"^\s*(select|with)\b", re.I | re.S)
FORMATS = ("table", "md", "csv", "json", "html")
ALL = "*"

# ad_revenue_type as AppMetrica sends it: a name, or the AdType code
# (0 unknown, 1 native, 2 banner, 3 rewarded, 4 interstitial, 5 mrec, 6 other).
AD_KINDS = {
    "interstitial": ("interstitial", "4"),
    "rewarded": ("rewarded", "rewarded_video", "3"),
    "banner": ("banner", "mrec", "2", "5"),
}


# --------------------------------------------------------------------------- #
# population
# --------------------------------------------------------------------------- #

@dataclass
class Device:
    first_date: str
    version: str
    country: str


@dataclass
class Population:
    devices: dict[str, Device]
    source: str                # which population: "v_players", "every device", the SELECT
    since: str | None
    until: str | None
    rate: float                # share of devices in the database (1.0 = all)
    last_date: str | None      # last loaded day of events (usually incomplete)
    filters: list[str] = field(default_factory=list)

    @property
    def window(self) -> tuple[str, str]:
        dates = [d.first_date for d in self.devices.values()]
        return (self.since or min(dates), self.until or max(dates))


def _relation(conn: sqlite3.Connection, spec: str, columns: str, what: str) -> str:
    """A view / table name or a SELECT -> a SELECT of `columns` from it (checked)."""
    text = spec.strip().rstrip(";").strip()
    if IDENT_RE.match(text):
        name = ".".join(store.quote(part) for part in text.split("."))
        sql = f"SELECT {columns} FROM {name}"
    elif SELECT_RE.match(text):
        sql = f"SELECT {columns} FROM ({text})"
    else:
        raise GakError(f"{what} '{spec}': give a view or table name, or a SELECT statement")
    try:
        conn.execute(f"SELECT * FROM ({sql}) LIMIT 0")
    except sqlite3.Error as error:
        raise GakError(f"{what} '{spec}' does not work: {error}; it must return {columns}") from None
    return sql


def load_population(conn: sqlite3.Connection, *, players: str | None = None, since: str | None = None,
                    until: str | None = None, version: str | None = None,
                    country: str | None = None) -> Population:
    """Devices whose first event falls in since..until, restricted to `players`.

    Leaves them in temp.gak_pop (device_id, first_date) for the queries that follow.
    """
    names = set(store.list_tables(conn)) | set(store.list_tables(conn, "view"))
    if "events" not in names or "v_device_first_seen" not in names:
        raise GakError("no events in this database yet; run `ga.py sync` first")
    if players is None and "v_players" in names:
        players = "v_players"
    source = players or "every device (the model has no v_players)"
    where, params = ["1 = 1"], {}
    if players:
        where.append(f"f.device_id IN ({_relation(conn, players, 'device_id', '--players')})")
    for key, value, column in (("since", since, "f.first_date >= :since"),
                               ("until", until, "f.first_date <= :until"),
                               ("version", version, "f.first_version = :version"),
                               ("country", country, "f.first_country = :country")):
        if value:
            where.append(column)
            params[key] = value
    rows = conn.execute(
        "SELECT f.device_id, f.first_date, COALESCE(f.first_version, ''), COALESCE(f.first_country, '') "
        f"FROM v_device_first_seen f WHERE {' AND '.join(where)}", params).fetchall()
    devices = {r[0]: Device(r[1], r[2], r[3]) for r in rows}
    filters = [f"{k} {v}" for k, v in (("version", version), ("country", country)) if v]
    if not devices:
        window = f"{since or '...'}..{until or '...'}"
        raise GakError(f"no devices with a first event in {window} in {source}"
                       + (f" ({', '.join(filters)})" if filters else ""))
    conn.execute("DROP TABLE IF EXISTS temp.gak_pop")
    conn.execute("CREATE TEMP TABLE gak_pop (device_id TEXT PRIMARY KEY, first_date TEXT)")
    conn.executemany("INSERT INTO temp.gak_pop VALUES (?, ?)",
                     ((d, dev.first_date) for d, dev in devices.items()))
    last = conn.execute("SELECT MAX(date) FROM events").fetchone()[0]
    return Population(devices, source, since, until, sample_rate(conn), last, filters)


def sample_rate(conn: sqlite3.Connection) -> float:
    if "meta" not in store.list_tables(conn):
        return 1.0
    value = conn.execute("SELECT MIN(CAST(value AS REAL)) FROM meta "
                         "WHERE key LIKE '%.sample_rate'").fetchone()[0]
    return 1.0 if value is None or value <= 0 else float(value)


def _life_filter(alias: str, life_days: int | None) -> str:
    if not life_days:
        return ""
    return f" AND {alias}.date < date(p.first_date, '+{int(life_days)} day')"


def session_times(conn: sqlite3.Connection, *, cap: int = DEFAULT_CAP, life_days: int | None = None,
                  scope: str = "all") -> dict[str, list[float]]:
    """Active seconds of every session of every device in temp.gak_pop.

    scope: all | first-day (events of the first day) | first-session (the session of the
    device's first event). A gap between two events of one session counts up to `cap`.
    """
    first_sid = (", FIRST_VALUE(sid) OVER (PARTITION BY device_id ORDER BY ts, id) AS first_sid"
                 if scope == "first-session" else "")
    keep = {"all": "1 = 1", "first-day": "day = first_date",
            "first-session": "sid IS first_sid"}[scope]
    sql = f"""
        WITH ev AS (
            SELECT e.appmetrica_device_id AS device_id, e.session_id AS sid, e.event_timestamp AS ts,
                   e.id AS id, e.date AS day, p.first_date AS first_date
            FROM events e JOIN temp.gak_pop p ON p.device_id = e.appmetrica_device_id
            WHERE e.event_timestamp IS NOT NULL{_life_filter('e', life_days)}
        ),
        g AS (
            SELECT device_id, sid, day, first_date,
                   ts - LAG(ts) OVER (PARTITION BY device_id, sid ORDER BY ts, id) AS gap{first_sid}
            FROM ev
        )
        SELECT device_id, SUM(MIN(COALESCE(gap, 0), :cap)) FROM g WHERE {keep}
        GROUP BY device_id, sid"""
    out: dict[str, list[float]] = {}
    for device, seconds in conn.execute(sql, {"cap": int(cap)}):
        out.setdefault(device, []).append(float(seconds or 0))
    return out


# --------------------------------------------------------------------------- #
# key metrics
# --------------------------------------------------------------------------- #

@dataclass
class Row:
    key: str
    unit: str                                   # count | pct | min | num | usd
    values: dict[str, float | None]
    n: dict[str, int] = field(default_factory=dict)        # base of a rate (DN)
    median: dict[str, float | None] = field(default_factory=dict)
    estimate: bool = False


@dataclass
class KeyMetrics:
    by: str
    groups: list[str]                            # column keys in order; ALL = every player
    rows: list[Row]
    population: Population
    cap: int
    life_days: int | None
    notes: list[str]


def _version_key(text: str) -> tuple:
    return tuple((0, int(p)) if p.isdigit() else (1, p) for p in re.split(r"[.\-_ ]", text))


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def _p90(values: list[float]) -> float | None:
    if not values:
        return None
    return statistics.quantiles(values, n=10)[-1] if len(values) >= 10 else max(values)


def _has_rows(conn: sqlite3.Connection, table: str, columns: tuple[str, ...]) -> bool:
    have = set(store.table_columns(conn, table))
    if not have or not set(columns) <= have:
        return False
    return conn.execute(f"SELECT EXISTS (SELECT 1 FROM {store.quote(table)} t "
                        "JOIN temp.gak_pop p ON p.device_id = t.appmetrica_device_id)").fetchone()[0] == 1


def key_metrics(conn: sqlite3.Connection, *, by: str = "version", top: int = 6, players: str | None = None,
                since: str | None = None, until: str | None = None, life_days: int | None = None,
                cap: int = DEFAULT_CAP, min_devices: int = 10) -> KeyMetrics:
    pop = load_population(conn, players=players, since=since, until=until)
    notes: list[str] = []

    def group_of(device: Device) -> str:
        value = device.version if by == "version" else device.country if by == "country" else ""
        return value or "(none)"

    groups: list[str] = []
    if by != "none":
        sizes: dict[str, int] = {}
        for device in pop.devices.values():
            sizes[group_of(device)] = sizes.get(group_of(device), 0) + 1
        kept = [g for g in sorted(sizes, key=lambda g: -sizes[g])[:max(top, 1)] if sizes[g] >= min_devices]
        dropped = [g for g in sizes if g not in kept]
        if dropped:
            notes.append(f"{len(dropped)} {by} group(s) below the top {top} or under {min_devices} devices "
                         f"({', '.join(sorted(dropped, key=lambda g: -sizes[g])[:5])}"
                         f"{', ...' if len(dropped) > 5 else ''}; {sum(sizes[g] for g in dropped)} device(s)) "
                         f"count only in the all-players column")
        groups = sorted(kept, key=_version_key) if by == "version" else kept
    groups.append(ALL)
    members = {g: [d for d, dev in pop.devices.items() if g == ALL or group_of(dev) == g] for g in groups}

    sessions = session_times(conn, cap=cap, life_days=life_days)
    returned: dict[str, set[int]] = {}
    for device, offset in conn.execute(
            "SELECT DISTINCT e.appmetrica_device_id, "
            "CAST(julianday(e.date) - julianday(p.first_date) AS INTEGER) "
            "FROM events e JOIN temp.gak_pop p ON p.device_id = e.appmetrica_device_id "
            f"WHERE julianday(e.date) - julianday(p.first_date) IN {tuple(RETENTION_DAYS)}"):
        returned.setdefault(device, set()).add(offset)
    last = date.fromisoformat(pop.last_date) if pop.last_date else None

    ads: dict[str, dict[str, list[float]]] = {}  # device -> kind -> [impressions, revenue]
    ad_kinds_seen: set[str] = set()
    has_ads = _has_rows(conn, "ad_revenue_events", ("ad_revenue_type", "ad_revenue"))
    if has_ads:
        currencies = set()
        for device, kind, count, revenue, currency in conn.execute(
                "SELECT a.appmetrica_device_id, LOWER(TRIM(COALESCE(a.ad_revenue_type, ''))), COUNT(*), "
                "SUM(COALESCE(a.ad_revenue, 0)), UPPER(COALESCE(a.ad_revenue_currency, '')) "
                "FROM ad_revenue_events a JOIN temp.gak_pop p ON p.device_id = a.appmetrica_device_id "
                f"WHERE 1 = 1{_life_filter('a', life_days)} GROUP BY 1, 2, 5"):
            name = next((k for k, codes in AD_KINDS.items() if kind in codes), "other")
            ad_kinds_seen.add(name)
            slot = ads.setdefault(device, {}).setdefault(name, [0.0, 0.0])
            slot[0] += count
            slot[1] += revenue or 0.0
            currencies.add(currency)
        if currencies - {"USD", ""}:
            notes.append(f"ad revenue currencies {sorted(currencies)}: summed as sent, not converted")
    else:
        notes.append("ad_revenue_events has no rows for these devices (not synced?): ad rows are empty")

    iap: dict[str, list[float]] = {}
    if _has_rows(conn, "revenue_events", ("revenue_price", "revenue_currency")):
        other = 0
        for device, currency, count, revenue in conn.execute(
                "SELECT r.appmetrica_device_id, UPPER(COALESCE(r.revenue_currency, '')), COUNT(*), "
                "SUM(COALESCE(r.revenue_price, 0) * COALESCE(NULLIF(r.revenue_quantity, 0), 1)) "
                "FROM revenue_events r JOIN temp.gak_pop p ON p.device_id = r.appmetrica_device_id "
                f"WHERE 1 = 1{_life_filter('r', life_days)} GROUP BY 1, 2"):
            if currency != "USD":
                other += count
                continue
            slot = iap.setdefault(device, [0.0, 0.0])
            slot[0] += count
            slot[1] += revenue or 0.0
        if other:
            notes.append(f"{other} IAP row(s) in other currencies are not counted in IAP revenue")
        notes.append("IAP = revenue_events rows as sent (price x quantity): check them for test "
                     "purchases and duplicates before quoting")

    rate = pop.rate
    rows: list[Row] = []

    def add(key: str, unit: str, fn, *, estimate: bool = False) -> None:
        """fn(devices of a group) -> (value, median or None, n or None)."""
        row = Row(key, unit, {}, estimate=estimate)
        for g in groups:
            value, median, base = fn(members[g])
            row.values[g] = value
            if median is not None:
                row.median[g] = median
            if base is not None:
                row.n[g] = base
        rows.append(row)

    def spread(values: list[float]) -> tuple[float | None, float | None, None]:
        return _mean(values), _median(values), None

    def ad_count(m: list[str], kind: str) -> float:
        return sum(ads.get(d, {}).get(kind, [0, 0])[0] for d in m)

    def ad_revenue(m: list[str]) -> float:
        return sum(v[1] for d in m for v in ads.get(d, {}).values())

    def iap_revenue(m: list[str]) -> float:
        return sum(iap[d][1] for d in m if d in iap)

    def retention(m: list[str], n_day: int) -> tuple[float | None, None, int]:
        base = [d for d in m if last and (last - date.fromisoformat(pop.devices[d].first_date)).days > n_day]
        share = 100.0 * sum(n_day in returned.get(d, ()) for d in base) / len(base) if base else None
        return share, None, len(base)

    add("players", "count", lambda m: (float(len(m)), None, None))
    if rate < 1:
        add("players_est", "count", lambda m: (len(m) / rate, None, None), estimate=True)
    for n_day in RETENTION_DAYS:
        add(f"d{n_day}", "pct", lambda m, n_day=n_day: retention(m, n_day))
    add("playtime", "min", lambda m: spread([sum(sessions.get(d, [])) / 60 for d in m]))
    add("sessions", "num", lambda m: spread([float(len(sessions.get(d, []))) for d in m]))
    add("session_len", "min", lambda m: spread([s / 60 for d in m for s in sessions.get(d, [])]))
    for kind in ("interstitial", "rewarded", "banner", "other"):
        if kind in ("interstitial", "rewarded") or kind in ad_kinds_seen:
            add(f"ads_{kind}", "num", lambda m, kind=kind: (
                ad_count(m, kind) / len(m) if has_ads else None, None, None))
    add("arpu", "usd", lambda m: (ad_revenue(m) / len(m) if has_ads else None, None, None))
    add("revenue", "usd", lambda m: (ad_revenue(m) if has_ads else None, None, None))
    if rate < 1:
        add("revenue_est", "usd", lambda m: (ad_revenue(m) / rate if has_ads else None, None, None),
            estimate=True)
    if iap:
        add("iap_payers", "count", lambda m: (float(sum(d in iap for d in m)), None, None))
        add("iap_revenue", "usd", lambda m: (iap_revenue(m), None, None))
        if rate < 1:
            add("iap_revenue_est", "usd", lambda m: (iap_revenue(m) / rate, None, None), estimate=True)
    return KeyMetrics(by, groups, rows, pop, cap, life_days, notes)


# --------------------------------------------------------------------------- #
# drop-off
# --------------------------------------------------------------------------- #

@dataclass
class DropRow:
    section: str             # "steps" | "time"
    label: str               # step name, or m:ss of active time
    reached: int
    lost: int | None         # reached at the previous row - reached here
    lost_pct: float | None   # lost as % of the previous row
    reached_pct: float       # reached as % of the cohort
    seconds: int | None = None
    sec_median: float | None = None   # time the step took (steps view with a `sec` column)
    sec_p90: float | None = None
    sec_max: float | None = None


@dataclass
class Dropoff:
    rows: list[DropRow]
    population: Population
    scope: str
    cap: int
    steps_source: str | None
    notes: list[str]


def _clock(seconds: int) -> str:
    return f"{seconds // 60}:{seconds % 60:02d}"


def dropoff(conn: sqlite3.Connection, *, players: str | None = None, steps: str | None = None,
            since: str | None = None, until: str | None = None, version: str | None = None,
            country: str | None = None, step_sec: int = 30, max_sec: int = 600,
            scope: str = "all", cap: int = DEFAULT_CAP) -> Dropoff:
    if step_sec <= 0 or max_sec < step_sec:
        raise GakError("--step-sec must be positive and not larger than --max-sec")
    pop = load_population(conn, players=players, since=since, until=until, version=version,
                          country=country)
    total = len(pop.devices)
    notes: list[str] = []
    rows: list[DropRow] = []

    def chain(section: str, items: list[tuple[str, int, int | None]]) -> None:
        previous = total
        rows.append(DropRow(section, "", total, None, None, 100.0))
        for label, reached, seconds in items:
            lost = previous - reached
            rows.append(DropRow(section, label, reached, lost,
                                100.0 * lost / previous if previous else None,
                                100.0 * reached / total, seconds))
            previous = reached

    if steps:
        try:  # an optional `sec` column = how long the step took (loading step time)
            sql, timed = _relation(conn, steps, "device_id, step_no, step_name, sec", "--steps"), True
        except GakError:
            sql, timed = _relation(conn, steps, "device_id, step_no, step_name", "--steps"), False
        best: dict[str, float] = {}
        names: dict[float, dict[str, int]] = {}
        secs: dict[float, list[float]] = {}
        for row in conn.execute(
                f"SELECT s.device_id, s.step_no, s.step_name{', s.sec' if timed else ''} FROM ({sql}) s "
                "JOIN temp.gak_pop p ON p.device_id = s.device_id WHERE s.step_no IS NOT NULL"):
            device, step_no, name = row[0], row[1], row[2]
            number = float(step_no)
            best[device] = max(best.get(device, number), number)
            counts = names.setdefault(number, {})
            counts[str(name)] = counts.get(str(name), 0) + 1
            if timed and row[3] is not None:
                try:
                    secs.setdefault(number, []).append(float(str(row[3]).replace(",", ".")))
                except ValueError:
                    pass
        if not names:
            notes.append("--steps returned no rows for these devices")
        items = []
        for number in sorted(names):
            label = max(names[number], key=names[number].get)
            items.append((label, sum(1 for v in best.values() if v >= number), None))
        chain("steps", items)
        for row, number in zip([r for r in rows if r.section == "steps" and r.label], sorted(names)):
            values = sorted(secs.get(number, []))
            if values:
                row.sec_median, row.sec_p90, row.sec_max = _median(values), _p90(values), values[-1]

    per_session = session_times(conn, cap=cap, scope=scope)
    active = [sum(per_session.get(d, [])) for d in pop.devices]
    chain("time", [(_clock(t), sum(1 for a in active if a >= t), t)
                   for t in range(step_sec, max_sec + 1, step_sec)])

    if "installations" in store.list_tables(conn) and pop.window:
        lo, hi = pop.window
        silent = conn.execute(
            "SELECT COUNT(DISTINCT i.appmetrica_device_id) FROM installations i "
            "WHERE i.date BETWEEN ? AND ? AND i.appmetrica_device_id <> '' AND NOT EXISTS "
            "(SELECT 1 FROM events e WHERE e.appmetrica_device_id = i.appmetrica_device_id)",
            (lo, hi)).fetchone()[0]
        if silent:
            notes.append(f"{silent} device(s) installed in {lo}..{hi} but sent no event: "
                         "they are not in the cohort (lost before the first event)")
    return Dropoff(rows, pop, scope, cap, steps, notes)


# --------------------------------------------------------------------------- #
# rendering
# --------------------------------------------------------------------------- #

TEXT = {
    "ru": {
        "players": "Игроков (устройств)", "players_s": "Игроков в выборке",
        "players_est": "Игроков, оценка ×{k}",
        "d1": "Retention D1", "d3": "Retention D3", "d7": "Retention D7",
        "playtime": "Время в игре на игрока, мин", "sessions": "Сессий на игрока",
        "session_len": "Средняя длина сессии, мин",
        "ads_interstitial": "Интерстишалов на игрока", "ads_rewarded": "Ревардов на игрока",
        "ads_banner": "Баннеров на игрока", "ads_other": "Прочей рекламы на игрока",
        "arpu": "ARPU (реклама), $", "revenue": "Доход с рекламы, $", "revenue_s": "Доход с рекламы в выборке, $",
        "revenue_est": "Доход с рекламы, оценка ×{k}, $",
        "iap_payers": "Платящих (IAP)", "iap_revenue": "Доход IAP, $", "iap_revenue_est": "Доход IAP, оценка ×{k}, $",
        "metric": "Метрика", "all": "Все игроки", "median": "медиана", "n": "n",
        "by_version": "версия первого события", "by_country": "страна первого события",
        "km_note": ("Когорта — устройства с первым событием {since} — {until} ({source}); столбцы — {by}. "
                    "D1/D3/D7 — событие на 1/3/7-й день после первого, считается только по устройствам, "
                    "чей этот день уже закончился (n под значением). Время в игре — сумма пауз между "
                    "событиями внутри сессии, каждая не больше {cap}; сессия — session_id AppMetrica{life}. "
                    "Реклама — ad_revenue_events, доход в долларах как прислан."),
        "life": ", только первые {n} дн. жизни",
        "sample": " Выборка {pct} устройств: строки «оценка» = выборка × {k}, доли и средние на игрока не пересчитываются.",
        "cohort": "Когорта: первое событие", "step": "Шаг", "time": "Активное время, мин:с",
        "reached": "Дошло", "lost": "Ушло", "lost_pct": "Ушло, % от предыдущего",
        "reached_pct": "Дошло, % от когорты", "reached_est": "Дошло, оценка",
        "step_time": "Время шага, с: медиана · p90 · макс",
        "drop_note": ("Когорта — {n} устройств с первым событием {since} — {until} ({source}{filters}). "
                      "Шаг засчитан, если устройство дошло до него или дальше. Активное время — сумма пауз "
                      "между событиями внутри сессии, каждая не больше {cap}; {scope}."),
        "scope_all": "все сессии устройства", "scope_first-day": "только первый день",
        "scope_first-session": "только первая сессия",
        "chart_title": "Какая доля игроков уходит в каждые {step} с активного времени",
        "chart_x": "активное время, мин:с · доля ушедших от доживших до начала интервала · n = {n}",
        "cap_text": "{m} мин",
    },
    "en": {
        "players": "Players (devices)", "players_s": "Players in the sample",
        "players_est": "Players, estimate ×{k}",
        "d1": "Retention D1", "d3": "Retention D3", "d7": "Retention D7",
        "playtime": "Active time per player, min", "sessions": "Sessions per player",
        "session_len": "Average session, min",
        "ads_interstitial": "Interstitials per player", "ads_rewarded": "Rewarded per player",
        "ads_banner": "Banners per player", "ads_other": "Other ads per player",
        "arpu": "ARPU (ads), $", "revenue": "Ad revenue, $", "revenue_s": "Ad revenue in the sample, $",
        "revenue_est": "Ad revenue, estimate ×{k}, $",
        "iap_payers": "Payers (IAP)", "iap_revenue": "IAP revenue, $", "iap_revenue_est": "IAP revenue, estimate ×{k}, $",
        "metric": "Metric", "all": "All players", "median": "median", "n": "n",
        "by_version": "version of the first event", "by_country": "country of the first event",
        "km_note": ("Cohort: devices whose first event is in {since} — {until} ({source}); columns: {by}. "
                    "D1/D3/D7: an event on day 1/3/7 after the first, over devices whose day is over "
                    "(n under the value). Active time: gaps between events inside a session, each capped "
                    "at {cap}; a session is an AppMetrica session_id{life}. Ads: ad_revenue_events, "
                    "revenue in USD as sent."),
        "life": ", first {n} life days only",
        "sample": " A {pct} device sample: 'estimate' rows = sample × {k}; rates and per-player values stay as they are.",
        "cohort": "Cohort: first event", "step": "Step", "time": "Active time, m:ss",
        "reached": "Reached", "lost": "Lost", "lost_pct": "Lost, % of previous",
        "reached_pct": "Reached, % of cohort", "reached_est": "Reached, estimate",
        "step_time": "Step time, s: median · p90 · max",
        "drop_note": ("Cohort: {n} devices whose first event is in {since} — {until} ({source}{filters}). "
                      "A step counts when the device reached it or a later one. Active time: gaps between "
                      "events inside a session, each capped at {cap}; {scope}."),
        "scope_all": "every session of the device", "scope_first-day": "the first day only",
        "scope_first-session": "the first session only",
        "chart_title": "Share of players who leave in each {step} s of active time",
        "chart_x": "active time, m:ss · share lost of those who reached the interval · n = {n}",
        "cap_text": "{m} min",
    },
}


def _t(lang: str) -> dict:
    return TEXT["ru" if lang == "ru" else "en"]


def source_label(source: str, lang: str) -> str:
    """How a population or event relation is named in a report note: a SELECT is not shown."""
    if SELECT_RE.match(source or ""):
        return "фильтр игроков проекта (см. методику)" if lang == "ru" else "the project's filter (see the method)"
    return source


def _fmt_date(value: str | None, lang: str) -> str:
    s = value or "…"
    return f"{s[8:10]}.{s[5:7]}.{s[:4]}" if lang == "ru" and re.match(r"^\d{4}-\d{2}-\d{2}$", s) else s


def _k(rate: float) -> str:
    k = 1 / rate
    return f"{k:.0f}" if abs(k - round(k)) < 0.05 else f"{k:.1f}"


def _share(rate: float, lang: str) -> str:
    from .report import charts
    pct = rate * 100
    return charts.fmt_num(pct, 0 if abs(pct - round(pct)) < 1e-9 else 1, lang) + "%"


def _plain(value: float | None, unit: str) -> str:
    if value is None:
        return "-"
    if unit == "count":
        return f"{value:,.0f}"
    if unit == "pct":
        return f"{value:.1f}%"
    if unit == "usd":
        return "$0" if value == 0 else f"${value:,.4f}" if abs(value) < 0.01 else f"${value:,.2f}"
    return f"{value:.2f}"


def _label(key: str, lang: str, rate: float) -> str:
    text = _t(lang)
    if rate < 1 and key in ("players", "revenue"):
        key += "_s"
    return text[key].format(k=_k(rate))


def _km_plain(km: KeyMetrics) -> query.Result:
    heads = ["metric"] + [("all" if g == ALL else g) for g in km.groups]
    table = []
    for row in km.rows:
        cells = [_label(row.key, "en", km.population.rate)]
        for g in km.groups:
            text = _plain(row.values.get(g), row.unit)
            if row.n:
                text += f" (n={row.n.get(g, 0)})"
            elif row.median and row.median.get(g) is not None:
                text += f" (median {row.median[g]:.2f})"
            cells.append(("~" if row.estimate and text != "-" else "") + text)
        table.append(cells)
    return query.Result(heads, table)


def render_key_metrics(km: KeyMetrics, fmt: str, lang: str) -> str:
    pop = km.population
    if fmt == "json":
        return json.dumps({
            "by": km.by, "groups": km.groups, "sample_rate": pop.rate, "population": pop.source,
            "window": list(pop.window), "last_loaded_day": pop.last_date, "cap_sec": km.cap,
            "life_days": km.life_days, "notes": km.notes,
            "rows": [{"key": r.key, "unit": r.unit, "estimate": r.estimate, "values": r.values,
                      "n": r.n or None, "median": r.median or None} for r in km.rows],
        }, ensure_ascii=False, indent=1)
    if fmt == "html":
        return _km_html(km, lang)
    buffer = io.StringIO()
    query.render(_km_plain(km), fmt, buffer)
    if fmt == "table":
        buffer.write(_km_footer(km))
    return buffer.getvalue()


def _km_footer(km: KeyMetrics) -> str:
    pop = km.population
    since, until = pop.window
    lines = [f"cohort: {len(pop.devices):,} device(s) with a first event in {since}..{until} from "
             f"{pop.source}; columns by {km.by}; last loaded day {pop.last_date} (incomplete)"]
    if pop.rate < 1:
        lines.append(f"sample: {pop.rate:.0%} of devices; '~' rows are estimates = sample x {_k(pop.rate)}")
    lines += [f"note: {n}" for n in km.notes]
    return "\n".join(lines) + "\n"


def _cell_html(row: Row, g: str, lang: str) -> str:
    from .report import charts
    text = _t(lang)
    value = row.values.get(g)
    if value is None:
        main = "—"
    elif row.unit == "count":
        main = charts.fmt_num(value, 0, lang)
    elif row.unit == "pct":
        main = charts.fmt_num(value, 1, lang) + "%"
    elif row.unit == "usd":
        main = "$0" if value == 0 else charts.fmt_money(value, 4 if row.key == "arpu" else 2, lang)
    else:
        main = charts.fmt_num(value, 2 if row.unit == "num" else 1, lang)
    if row.estimate and value is not None:
        main = "≈ " + main
    extra = ""
    if row.n:
        extra = f"<small>{text['n']} = {charts.fmt_num(row.n.get(g, 0), 0, lang)}</small>"
    elif row.median.get(g) is not None:
        extra = f"<small>{text['median']} {charts.fmt_num(row.median[g], 1, lang)}</small>"
    cls = "n est" if row.estimate else "n"
    return f'<td class="{cls}">{html.escape(main)}{extra}</td>'


def _km_html(km: KeyMetrics, lang: str) -> str:
    text, pop = _t(lang), km.population
    heads = "".join(f'<th class="n">{html.escape(text["all"] if g == ALL else g)}</th>' for g in km.groups)
    body = []
    for row in km.rows:
        cells = "".join(_cell_html(row, g, lang) for g in km.groups)
        cls = ' class="est"' if row.estimate else ""
        body.append(f'    <tr{cls}><td>{html.escape(_label(row.key, lang, pop.rate))}</td>{cells}</tr>')
    since, until = pop.window
    by = text.get(f"by_{km.by}", text["all"])
    note = text["km_note"].format(
        since=_fmt_date(since, lang), until=_fmt_date(until, lang), source=html.escape(source_label(pop.source, lang)),
        by=by,
        cap=text["cap_text"].format(m=km.cap // 60) if km.cap % 60 == 0 else f"{km.cap} s",
        life=text["life"].format(n=km.life_days) if km.life_days else "")
    if pop.rate < 1:
        note += text["sample"].format(pct=_share(pop.rate, lang), k=_k(pop.rate))
    return ('<div class="tablebox">\n<table class="kpi">\n'
            f'  <thead><tr><th>{text["metric"]}</th>{heads}</tr></thead>\n  <tbody>\n'
            + "\n".join(body) + "\n  </tbody>\n</table>\n</div>\n"
            f'<p class="tnote">{note}</p>\n')


def _drop_plain(result: Dropoff) -> query.Result:
    rate = result.population.rate
    timed = any(r.sec_median is not None for r in result.rows)
    heads = ["section", "row", "reached", "lost", "lost_pct_of_previous", "reached_pct_of_cohort"]
    if rate < 1:
        heads.append("reached_estimate")
    if timed:
        heads += ["step_sec_median", "step_sec_p90", "step_sec_max"]
    table = []
    for r in result.rows:
        cells = [r.section, r.label or "cohort", r.reached, "" if r.lost is None else r.lost,
                 "" if r.lost_pct is None else round(r.lost_pct, 1), round(r.reached_pct, 1)]
        if rate < 1:
            cells.append(round(r.reached / rate))
        if timed:
            cells += ["" if v is None else round(v, 2) for v in (r.sec_median, r.sec_p90, r.sec_max)]
        table.append(cells)
    return query.Result(heads, table)


def render_dropoff(result: Dropoff, fmt: str, lang: str) -> str:
    pop = result.population
    if fmt == "json":
        return json.dumps({
            "sample_rate": pop.rate, "population": pop.source, "window": list(pop.window),
            "scope": result.scope, "cap_sec": result.cap, "steps": result.steps_source,
            "filters": pop.filters, "notes": result.notes,
            "rows": [r.__dict__ for r in result.rows],
        }, ensure_ascii=False, indent=1)
    if fmt == "html":
        return _drop_html(result, lang)
    buffer = io.StringIO()
    query.render(_drop_plain(result), fmt, buffer)
    if fmt == "table":
        since, until = pop.window
        buffer.write(f"cohort: {len(pop.devices):,} device(s) with a first event in {since}..{until} from "
                     f"{pop.source}{'; ' + ', '.join(pop.filters) if pop.filters else ''}; "
                     f"active time over {result.scope}, gaps capped at {result.cap} s\n")
        if pop.rate < 1:
            buffer.write(f"sample: {pop.rate:.0%} of devices; reached_estimate = reached x {_k(pop.rate)}\n")
        for note in result.notes:
            buffer.write(f"note: {note}\n")
    return buffer.getvalue()


def _drop_html(result: Dropoff, lang: str) -> str:
    from .report import charts
    text, pop = _t(lang), result.population
    parts = []
    for section in ("steps", "time"):
        rows = [r for r in result.rows if r.section == section]
        if not rows:
            continue
        worst = sorted((r for r in rows if r.lost_pct is not None), key=lambda r: -r.lost_pct)[:3]
        timed = any(r.sec_median is not None for r in rows)
        heads = [text["step"] if section == "steps" else text["time"], text["reached"], text["lost"],
                 text["lost_pct"], text["reached_pct"]] + ([text["reached_est"]] if pop.rate < 1 else []) \
            + ([text["step_time"]] if timed else [])
        body = []
        for r in rows:
            label = r.label or text["cohort"]
            bad = " bad" if r in worst and r.lost else ""
            cells = [f"<td>{html.escape(label)}</td>",
                     f'<td class="n">{charts.fmt_num(r.reached, 0, lang)}</td>',
                     f'<td class="n">{"—" if r.lost is None else charts.fmt_num(r.lost, 0, lang)}</td>',
                     f'<td class="n{bad}">{"—" if r.lost_pct is None else charts.fmt_num(r.lost_pct, 1, lang) + "%"}</td>',
                     f'<td class="n">{charts.fmt_num(r.reached_pct, 1, lang)}%</td>']
            if pop.rate < 1:
                cells.append(f'<td class="n est">≈ {charts.fmt_num(r.reached / pop.rate, 0, lang)}</td>')
            if timed:
                parts_ = [charts.fmt_num(v, 1 if v < 100 else 0, lang) for v in (r.sec_median, r.sec_p90, r.sec_max)
                          if v is not None]
                cells.append(f'<td class="n">{" · ".join(parts_) if parts_ else "—"}</td>')
            body.append(f"    <tr>{''.join(cells)}</tr>")
        head = f"<th>{heads[0]}</th>" + "".join(f'<th class="n">{h}</th>' for h in heads[1:])
        parts.append('<div class="tablebox">\n<table class="drop">\n'
                     f"  <thead><tr>{head}</tr></thead>\n  <tbody>\n" + "\n".join(body)
                     + "\n  </tbody>\n</table>\n</div>\n")
    since, until = pop.window
    cap = text["cap_text"].format(m=result.cap // 60) if result.cap % 60 == 0 else f"{result.cap} s"
    note = text["drop_note"].format(
        n=charts.fmt_num(len(pop.devices), 0, lang), since=_fmt_date(since, lang), until=_fmt_date(until, lang),
        source=html.escape(source_label(pop.source, lang)),
        filters=("; " + html.escape(", ".join(pop.filters))) if pop.filters else "",
        cap=cap, scope=text[f"scope_{result.scope}"])
    if pop.rate < 1:
        note += text["sample"].format(pct=_share(pop.rate, lang), k=_k(pop.rate))
    return "".join(parts) + f'<p class="tnote">{note}</p>\n'


def dropoff_svg(result: Dropoff, lang: str) -> str:
    from .report import charts
    text = _t(lang)
    rows = [r for r in result.rows if r.section == "time" and r.seconds]
    step = rows[0].seconds if rows else 30
    values = [r.lost_pct for r in rows]
    ranked = sorted(range(len(rows)), key=lambda i: -(values[i] or 0))[:3]
    return charts.bar([r.label for r in rows], values, unit="%", lang=lang, decimals=1,
                      highlight={i: "s-bad" for i in ranked},
                      title=text["chart_title"].format(step=step),
                      x_label=text["chart_x"].format(n=charts.fmt_num(len(result.population.devices), 0, lang)))
