"""event_json -> event_params rows.

Game parameters arrive as one JSON string per event (a flat dictionary in
AppMetrica's event_json). They are flattened once at load time into
event_params(key, value_text, value_num): json_extract over millions of rows is
slow, and "group by a parameter value" is the most common question.

Only valid JSON is kept in the json column; text that does not parse goes to
<field>_raw instead. json_extract raises on malformed JSON, so one broken event
would otherwise make every view over the column fail.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

EVENT_NAME_FIELD = "event_name"  # copied into event_params when the table has it

# Plain numbers only: "nan", "inf" or "1e5x" must stay text. A decimal comma is
# accepted because Unity on a Russian locale formats floats as "1,5".
_NUMBER_RE = re.compile(r"[+-]?(\d+([.,]\d*)?|[.,]\d+)([eE][+-]?\d+)?")


@dataclass(frozen=True)
class ParsedJson:
    normalized: str | None   # compact valid JSON, or None
    raw: str | None          # original text when it did not parse
    params: dict[str, Any] | None  # the dictionary to flatten, when it is one


def raw_column(json_field: str) -> str:
    return f"{json_field}_raw"


def parse_json(value: str | None) -> ParsedJson:
    if not value:
        return ParsedJson(None, None, None)
    try:
        parsed = json.loads(value)
    except (ValueError, TypeError):
        return ParsedJson(None, value, None)
    normalized = json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))
    return ParsedJson(normalized, None, parsed if isinstance(parsed, dict) else None)


def param_rows(event_id: int, day: str, load_date: str, event_name: str | None,
               params: dict[str, Any]) -> list[tuple]:
    """(event_id, date, load_date, event_name, key, value_text, value_num) per key."""
    rows = []
    for key, value in params.items():
        if isinstance(value, (dict, list)):
            text: str | None = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            number = None
        elif isinstance(value, bool):
            text, number = ("true" if value else "false"), float(value)
        else:
            text = None if value is None else str(value)
            number = as_number(value)
        rows.append((event_id, day, load_date, event_name, str(key), text, number))
    return rows


def as_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if _NUMBER_RE.fullmatch(text):
            return float(text.replace(",", "."))
    return None
