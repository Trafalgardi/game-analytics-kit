"""Generic CSV importer for console exports (Google Ads, AdMob, GA4, Play Console).

Console exports are messy in predictable ways, and each of these broke a
naive import once:
- encodings: UTF-8 with BOM, UTF-16 (Google consoles export tab-separated
  UTF-16), Windows-1251 from a Russian Excel;
- delimiters: `,`, `;` or tab, sometimes announced by an Excel `sep=;` line;
- a preamble above the header (report name, date range) and "Total" rows
  below the data;
- localized headers ("Стоимость/конв.") and localized numbers: `41 814`,
  `1 234,56`, `0,24 $`, `$0.24`, `US$1,234.56`, `11,23 %`, and `—` or `--`
  for "no value".
So an import keeps every column as raw text (nothing is lost), names columns
in ASCII snake_case (Cyrillic transliterated), and adds `<col>__num REAL` for
each column where at least 80% of non-empty values parse as numbers. Percent
values stay in percent units (11,23 % -> 11.23). The file, kind, sha256, row
count and preamble are recorded in `imports`; the same file is never imported
twice unless --replace.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
import sqlite3
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from . import GakError
from .store import now_iso, quote, table_columns, transaction

KINDS = ("google_ads", "admob", "ga4", "play_console", "generic")
NUMERIC_SHARE = 0.8
SNIFF_LINES = 50
DELIMITERS = (",", ";", "\t")

NULL_TOKENS = {"", "-", "--", "—", "–", "n/a", "na", "null", "none", "nan"}
CURRENCY_AFFIXES = {"", "$", "us$", "€", "£", "₽", "¥", "₴", "₸", "usd", "eur", "rub", "gbp",
                    "руб", "руб.", "р.", "р"}
TOTAL_ROW_RE = re.compile(r"^\s*(total|totals|итого|всего)\b", re.IGNORECASE)
_NUMBER_RE = re.compile(r"(?P<pre>[^\d]*?)(?P<num>\d(?:[\d ',.]*\d)?)(?P<post>[^\d]*)")
_SPACES = str.maketrans({"\u00a0": " ", "\u202f": " ", "\u2009": " ", "\u2007": " "})

_CYRILLIC = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts",
    "ч": "ch", "ш": "sh", "щ": "shch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu",
    "я": "ya", "і": "i", "ї": "yi", "є": "ye", "ґ": "g",
}
_SYMBOLS = {"%": " pct ", "#": " num ", "+": " plus ", "&": " and ", "$": " usd ", "€": " eur "}


@dataclass
class ImportResult:
    table: str
    import_id: int
    rows: int
    columns: list[str]
    numeric_columns: list[str]
    encoding: str
    delimiter: str
    preamble: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# naming and numbers
# --------------------------------------------------------------------------- #

def sanitize_name(text: str) -> str:
    """ASCII snake_case: 'Стоимость/конв.' -> 'stoimost_konv', 'CTR (%)' -> 'ctr_pct'."""
    out = []
    for char in text.strip().lower():
        char = _CYRILLIC.get(char, _SYMBOLS.get(char, char))
        out.append(char)
    ascii_text = unicodedata.normalize("NFKD", "".join(out)).encode("ascii", "ignore").decode()
    name = re.sub(r"[^a-z0-9]+", "_", ascii_text).strip("_")
    if name and name[0].isdigit():
        name = "c_" + name
    return name


def detect_decimal(values: list[str]) -> str | None:
    """',' or '.' as the file's decimal separator, from values that settle it."""
    comma = dot = 0
    for value in values:
        text = value.translate(_SPACES)
        last_comma, last_dot = text.rfind(","), text.rfind(".")
        if last_comma >= 0 and last_dot >= 0:
            comma, dot = (comma + 1, dot) if last_comma > last_dot else (comma, dot + 1)
            continue
        for sep in (",", "."):
            match = re.search(r"\d\{}(\d+)".format(sep), text)
            if match and len(match.group(1)) != 3 and text.count(sep) == 1:
                comma, dot = (comma + 1, dot) if sep == "," else (comma, dot + 1)
    if comma == dot:
        return None
    return "," if comma > dot else "."


def parse_number(text: str | None, decimal: str | None = None) -> float | None:
    """A console-formatted number, or None when the text is not one."""
    if text is None:
        return None
    value = text.translate(_SPACES).strip()
    if value.lower() in NULL_TOKENS:
        return None
    negative = False
    if value.startswith("(") and value.endswith(")"):
        negative, value = True, value[1:-1].strip()
    match = _NUMBER_RE.fullmatch(value)
    if not match:
        return None
    pre, post = match.group("pre").strip(), match.group("post").strip()
    if pre and (pre[0] in "-−" or pre[-1] in "-−"):
        negative = not negative
        pre = pre.strip("-−").strip()
    pre = pre.lstrip("+").strip()
    if pre.lower() not in CURRENCY_AFFIXES or post.lower() not in CURRENCY_AFFIXES | {"%"}:
        return None
    number = _normalize_digits(match.group("num"), decimal)
    if number is None:
        return None
    return -float(number) if negative else float(number)


def _normalize_digits(num: str, decimal: str | None) -> str | None:
    """Digits with separators -> a float literal; None when the grouping is not a number's.

    Thousands groups must have three digits, so a version "1.1.23" or a date
    "01.09.2026" stays text instead of becoming 1123 or 1092026.
    """
    if " " in num or "'" in num:
        if not re.fullmatch(r"\d{1,3}([ ']\d{3})+([.,]\d+)?", num):
            return None
        num = num.replace(" ", "").replace("'", "")
    commas, dots = num.count(","), num.count(".")
    if commas and dots:
        dec = "," if num.rfind(",") > num.rfind(".") else "."
        thousands = "." if dec == "," else ","
        integer, _, fraction = num.rpartition(dec)
        if dec in integer or not _grouped(integer, thousands):
            return None
        return integer.replace(thousands, "") + "." + fraction
    for sep, count in ((",", commas), (".", dots)):
        if not count:
            continue
        if count > 1:  # only thousands separators repeat
            return num.replace(sep, "") if _grouped(num, sep) else None
        integer, fraction = num.split(sep)
        other = "." if sep == "," else ","
        is_thousands = len(fraction) == 3 and len(integer) <= 3 and (
            decimal == other or (decimal is None and sep == ","))
        return num.replace(sep, "") if is_thousands else num.replace(sep, ".")
    return num


def _grouped(integer: str, sep: str) -> bool:
    head, *groups = integer.split(sep)
    if not groups:
        return bool(head)
    return 1 <= len(head) <= 3 and all(len(group) == 3 for group in groups)


# --------------------------------------------------------------------------- #
# reading the file
# --------------------------------------------------------------------------- #

def decode(data: bytes) -> tuple[str, str]:
    """(text, encoding): BOMs first, then UTF-16 without BOM, UTF-8, Windows-1251."""
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8"), "utf-8-sig"
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16"), "utf-16"
    head = data[:2000]
    if head and head.count(b"\x00") > len(head) // 4:
        encoding = "utf-16-le" if head[1:2] == b"\x00" else "utf-16-be"
        return data.decode(encoding), encoding
    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        return data.decode("cp1251"), "cp1251"


def sniff_delimiter(lines: list[str]) -> str:
    """The delimiter giving the most rows with one consistent column count."""
    best, best_score = ",", (-1, -1)
    sample = "\n".join(lines[:SNIFF_LINES])
    for delimiter in DELIMITERS:
        counts = [len(row) for row in csv.reader(io.StringIO(sample), delimiter=delimiter) if row]
        if not counts:
            continue
        modal = max(set(counts), key=lambda n: (counts.count(n), n))
        score = (counts.count(modal) if modal > 1 else 0, modal)
        if score > best_score:
            best, best_score = delimiter, score
    return best


def read_rows(text: str) -> tuple[list[list[str]], str]:
    lines = text.splitlines()
    delimiter = None
    if lines and lines[0].strip().lower().startswith("sep=") and len(lines[0].strip()) == 5:
        delimiter = lines[0].strip()[4]
        text = "\n".join(lines[1:])
        lines = lines[1:]
    delimiter = delimiter or sniff_delimiter(lines)
    rows = [row for row in csv.reader(io.StringIO(text), delimiter=delimiter)
            if any(cell.strip() for cell in row)]
    return rows, delimiter


def split_header(rows: list[list[str]]) -> tuple[list[str], list[str], list[list[str]]]:
    """(preamble lines, header, data rows): the header is the first row as wide as most rows."""
    if not rows:
        raise GakError("the file has no rows")
    counts = [len(row) for row in rows]
    modal = max(set(counts), key=lambda n: (counts.count(n), n))
    index = next(i for i, row in enumerate(rows) if len(row) == modal)
    preamble = [" ".join(cell.strip() for cell in row if cell.strip()) for row in rows[:index]]
    return preamble, rows[index], rows[index + 1:]


def column_names(header: list[str]) -> list[str]:
    names: list[str] = []
    taken = {"import_id", "row_no"}
    for index, title in enumerate(header, start=1):
        base = sanitize_name(title) or f"col_{index}"
        name, suffix = base, 2
        while name in taken:
            name, suffix = f"{base}_{suffix}", suffix + 1
        taken.add(name)
        names.append(name)
    return names


# --------------------------------------------------------------------------- #
# import
# --------------------------------------------------------------------------- #

def default_table(path: Path) -> str:
    return sanitize_name(path.stem) or "import"


def import_csv(conn: sqlite3.Connection, path: Path, *, kind: str = "generic",
               table: str | None = None, replace: bool = False,
               display_name: str | None = None) -> ImportResult:
    if kind not in KINDS:
        raise GakError(f"--kind must be one of {', '.join(KINDS)}")
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    name = "ext_" + (sanitize_name(table or "").removeprefix("ext_") or default_table(path))
    if not replace:
        _refuse_duplicate(conn, digest)

    text, encoding = decode(data)
    rows, delimiter = read_rows(text)
    preamble, header, body = split_header(rows)
    columns = column_names(header)
    data_rows, skipped = _clean_rows(body, len(columns))

    decimal = detect_decimal([cell for row in data_rows for cell in row if cell])
    numeric = [col for i, col in enumerate(columns)
               if _is_numeric([row[i] for row in data_rows], decimal)]

    with transaction(conn):
        if replace:
            conn.execute(f"DROP TABLE IF EXISTS {quote(name)}")
            conn.execute("DELETE FROM imports WHERE table_name = ?", (name,))
        numeric = _prepare_table(conn, name, columns, numeric)
        import_id = conn.execute(
            "INSERT INTO imports (file, kind, table_name, rows, imported_at, sha256, preamble) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (display_name or str(path), kind, name, len(data_rows), now_iso(), digest,
             "\n".join(preamble) or None)).lastrowid
        _insert(conn, name, import_id, columns, numeric, data_rows, decimal)
    return ImportResult(name, import_id, len(data_rows), columns, numeric, encoding,
                        {"\t": "tab"}.get(delimiter, delimiter), preamble, skipped)


def _clean_rows(body: list[list[str]], width: int) -> tuple[list[list[str | None]], list[str]]:
    """Data rows padded to the header width, without "Total" rows; plus notes on both."""
    rows: list[list[str | None]] = []
    totals: list[str] = []
    ragged = 0
    for row in body:
        first = next((cell.strip() for cell in row if cell.strip()), "")
        if TOTAL_ROW_RE.match(first):
            totals.append(first)
            continue
        if len(row) != width:
            ragged += 1
            row = (row + [""] * width)[:width]
        rows.append([cell.strip() or None for cell in row])
    notes = [f"skipped {len(totals)} total row(s): {'; '.join(totals[:3])}"] if totals else []
    if ragged:
        notes.append(f"{ragged} row(s) did not have {width} cells and were padded or cut")
    return rows, notes


def _refuse_duplicate(conn: sqlite3.Connection, digest: str) -> None:
    row = conn.execute("SELECT table_name, imported_at, file FROM imports WHERE sha256 = ?",
                       (digest,)).fetchone()
    if row:
        raise GakError(f"this file was already imported into {row[0]} on {row[1][:10]} "
                       f"(as {row[2]}); pass --replace to load it again")


def _is_numeric(values: list[str | None], decimal: str | None) -> bool:
    present = [v for v in values if v is not None and v.strip().lower() not in NULL_TOKENS]
    if not present:
        return False
    parsed = sum(parse_number(v, decimal) is not None for v in present)
    return parsed / len(present) >= NUMERIC_SHARE


def _prepare_table(conn: sqlite3.Connection, name: str, columns: list[str],
                   numeric: list[str]) -> list[str]:
    """Create the table, or check an existing one matches; returns the __num columns to fill."""
    existing = table_columns(conn, name)
    if not existing:
        definition = ["import_id INTEGER NOT NULL", "row_no INTEGER NOT NULL"]
        for column in columns:
            definition.append(f"{quote(column)} TEXT")
            if column in numeric:
                definition.append(f"{quote(column + '__num')} REAL")
        conn.execute(f"CREATE TABLE {quote(name)} ({', '.join(definition)})")
        return numeric
    raw = [c for c in existing if c not in ("import_id", "row_no") and not c.endswith("__num")]
    if raw != columns:
        raise GakError(f"{name} already exists with other columns; use --table NAME for a "
                       "separate table or --replace to rebuild it")
    for column in numeric:
        if column + "__num" not in existing:
            conn.execute(f"ALTER TABLE {quote(name)} ADD COLUMN {quote(column + '__num')} REAL")
    return sorted(set(numeric) | {c[:-5] for c in existing if c.endswith("__num")},
                  key=columns.index)


def _insert(conn: sqlite3.Connection, name: str, import_id: int, columns: list[str],
            numeric: list[str], rows: list[list[str | None]], decimal: str | None) -> None:
    targets = ["import_id", "row_no"]
    for column in columns:
        targets.append(column)
        if column in numeric:
            targets.append(column + "__num")
    sql = "INSERT INTO {} ({}) VALUES ({})".format(
        quote(name), ", ".join(quote(t) for t in targets), ", ".join("?" * len(targets)))
    batch = []
    for number, row in enumerate(rows, start=1):
        values: list[object] = [import_id, number]
        for column, cell in zip(columns, row):
            values.append(cell)
            if column in numeric:
                values.append(parse_number(cell, decimal))
        batch.append(values)
    conn.executemany(sql, batch)
