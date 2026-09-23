"""Source plugin interface.

A source knows three things: which tables it offers, which fields each table
has, and how to download one date range of one table into a CSV file on disk.
Everything else - deciding which days to request, replacing a range in SQLite,
the sync log, flattening event parameters, pruning fields the remote rejects -
is generic and lives in sync.py and store.py. Adding a second event source
(Firebase BigQuery export, GameAnalytics, devtodev, Amplitude) therefore means
one module implementing `Source` plus its field list, nothing else.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable, Mapping

from .. import GakError

Log = Callable[[str], None]

TEXT = "TEXT"
INTEGER = "INTEGER"
REAL = "REAL"


@dataclass(frozen=True)
class Table:
    """One remote table and the SQLite table it lands in (same name)."""

    name: str                       # table name in SQLite, e.g. "events"
    fields: list[str]               # requested fields, in order, PII excluded
    date_field: str                 # field whose date() fills the `date` column
    json_field: str | None = None   # field flattened into event_params
    default: bool = False           # part of the default sync set
    pii_fields: list[str] = field(default_factory=list)  # only with --with-device-ids
    types: Mapping[str, str] = field(default_factory=dict)  # SQLite type per field, TEXT if absent
    device_field: str | None = None  # identifies the device: sampling keeps or drops whole devices

    def all_fields(self) -> list[str]:
        """Every field a column exists for, PII included (columns stay NULL without it)."""
        return list(self.fields) + list(self.pii_fields)

    def requested_fields(self, with_pii: bool) -> list[str]:
        return list(self.fields) + (list(self.pii_fields) if with_pii else [])

    def column_type(self, name: str) -> str:
        return self.types.get(name, TEXT)


class SourceError(GakError):
    """The remote failed in a way the user has to fix (token, access, quota)."""


class RequestRejected(SourceError):
    """The remote refused the request itself (for HTTP sources: a 400).

    `text` is the remote's answer. sync.py asks the source which requested
    fields the answer names, drops them and retries: API docs drift, and a
    missing column is better than a failed sync.
    """

    def __init__(self, message: str, text: str):
        super().__init__(message)
        self.text = text


class Source(ABC):
    """A remote analytics source.

    Constructed as cls(options, token, token_origin, log) with every argument
    optional: options is the [sources.<name>] table of analytics.toml, and
    schema creation builds an instance without a token. No network in __init__.
    """

    name: str = ""
    token_env: str = ""   # environment variable / .env key holding the credential

    @abstractmethod
    def tables(self) -> list[Table]:
        """Every table this source can deliver; `default` marks the usual set."""

    @abstractmethod
    def check(self) -> str:
        """Human-readable "who am I connected to" line, no secrets."""

    def applications(self) -> list[dict[str, str]]:
        """Apps the credential can see: id, name, api_key, created, timezone (`ga.py apps`)."""
        raise GakError(f"{self.name} cannot list applications")

    def connect(self) -> dict[str, str]:
        """Resolve the remote account / app before a sync.

        Returns facts worth keeping in the `meta` table (stored as
        "<source>.<key>"), e.g. app id, name and time zone.
        """
        return {}

    def first_day(self) -> date | None:
        """Earliest day that can hold data (e.g. app creation), after connect()."""
        return None

    @abstractmethod
    def fetch(self, table: Table, fields: list[str], start: date, end: date,
              dest: Path, log: Log, *, fresh: bool = False) -> Path:
        """Write rows of [start, end] (whole days, inclusive) as CSV with a header.

        `fresh` means the range is still inside the late-delivery window or
        was loaded while it was: the remote must rebuild it, not replay a
        cached answer. Raise RequestRejected when the remote refuses the
        request, SourceError for anything the user has to fix.
        """

    def warm(self, table: Table, fields: list[str], start: date, end: date) -> None:
        """Optional hint: start preparing a range that will be fetched next.

        Called from a background thread; must not raise and must not share
        connection state with fetch().
        """

    def rejected_fields(self, error_text: str, fields: list[str]) -> list[str]:
        """Fields a RequestRejected answer complains about (empty = not a field problem)."""
        return []

    def table(self, name: str) -> Table:
        for table in self.tables():
            if table.name == name:
                return table
        known = ", ".join(t.name for t in self.tables())
        raise GakError(f"{self.name} has no table '{name}'; known: {known}")
