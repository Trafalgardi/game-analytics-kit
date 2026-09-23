"""AppMetrica source: Logs API exports and the Management API app lookup.

Contract and pitfalls (docs/KNOWLEDGE.md section A):
- GET /logs/v1/export/<table>.csv with application_id, date_since, date_until,
  date_dimension=default (event time) and fields=a,b,c; the token goes in
  "Authorization: OAuth <token>", never in the URL.
- The numeric application_id is not the SDK key found in the game code:
  /management/v1/applications lists every app of the token with its api_key,
  and the one matching analytics.toml is used (app_id there wins).
- 202 (preparing) and 429 (three exports already queued) are waited out by
  http.py. A 400 "Try to use more parts" means the range is too big for one
  file: retry with parts_count doubled and glue the parts into one CSV.
- skip_unavailable_shards=true thins the answer instead of failing it; should
  the API ever reject the flag, retry without it.
- 401 = token missing, expired or without appmetrica:read.
- Dates are in the app's time zone (time_zone_name, kept in meta).
"""

from __future__ import annotations

import os
import re
import shutil
from datetime import date, datetime
from pathlib import Path
from typing import BinaryIO, Mapping

from ..http import Http, HttpError, build_url, human_size
from .appmetrica_fields import TABLES
from .base import Log, RequestRejected, Source, SourceError, Table

HOST = "https://api.appmetrica.yandex.ru"
MAX_PARTS = 64
CONNECT_SKILL = "analytics-connect-appmetrica"


def _print(message: str) -> None:
    print(message, flush=True)


class AppMetricaSource(Source):
    name = "appmetrica"
    token_env = "APPMETRICA_TOKEN"

    def __init__(self, options: Mapping[str, object] | None = None, token: str | None = None,
                 token_origin: str = "", log: Log = _print, *, http: Http | None = None,
                 host: str = HOST):
        options = options or {}
        self._api_key = str(options.get("api_key") or "").strip()
        self._app_id = str(options.get("app_id") or "").strip()
        self._token = token
        self._token_origin = token_origin
        self._log = log
        self._http = http or Http()
        self._host = host.rstrip("/")
        self._app: dict[str, str] | None = None

    # -- interface ---------------------------------------------------------- #

    def tables(self) -> list[Table]:
        return list(TABLES)

    def check(self) -> str:
        if self._app is None:
            return "appmetrica: not connected yet"
        return (f'appmetrica: app {self._app["id"]} "{self._app["name"] or "?"}" '
                f'(time zone {self._app["timezone"] or "?"}), token from {self._token_origin}')

    def applications(self) -> list[dict[str, str]]:
        """Every app the token can see: id, name, api_key, created, timezone."""
        try:
            data = self._http.get_json(f"{self._host}/management/v1/applications",
                                       self._headers(), self._log)
        except HttpError as error:
            raise self._translate(error) from None
        return [_app_row(app) for app in (data or {}).get("applications", [])]

    def connect(self) -> dict[str, str]:
        self._app = self._resolve_app()
        return {
            "app_id": self._app["id"],
            "app_name": self._app["name"],
            "api_key": self._app["api_key"],
            "app_created": self._app["created"],
            "timezone": self._app["timezone"],
        }

    def first_day(self) -> date | None:
        created = (self._app or {}).get("created", "")[:10]
        try:
            return datetime.strptime(created, "%Y-%m-%d").date()
        except ValueError:
            return None

    def fetch(self, table: Table, fields: list[str], start: date, end: date,
              dest: Path, log: Log, *, fresh: bool = False) -> Path:
        app_id = self._require_app_id()
        parts = 1
        skip_shards = True
        while True:
            params = export_params(app_id, fields, start, end, skip_shards)
            try:
                self._download(table.name, params, parts, fresh, dest, log)
                return dest
            except HttpError as error:
                if error.status == 400 and "more parts" in error.text:
                    if parts >= MAX_PARTS:
                        raise SourceError(f"{table.name} {start}..{end} is too big even in "
                                          f"{parts} parts; use a smaller --chunk-days") from None
                    parts *= 2
                    log(f"      export too large, splitting into {parts} parts")
                    continue
                if error.status == 400 and skip_shards and "skip_unavailable_shards" in error.text:
                    skip_shards = False
                    log("      API rejected skip_unavailable_shards, retrying without it")
                    continue
                raise self._translate(error) from None

    def warm(self, table: Table, fields: list[str], start: date, end: date) -> None:
        try:
            params = export_params(self._require_app_id(), fields, start, end, True)
            url = build_url(f"{self._host}/logs/v1/export/{table.name}.csv", params)
            self._http.touch(url, self._headers())
        except Exception:  # noqa: BLE001 - a failed warm-up is reported by the real request
            pass

    def rejected_fields(self, error_text: str, fields: list[str]) -> list[str]:
        return [name for name in fields
                if re.search(r"\b{}\b".format(re.escape(name)), error_text)]

    # -- internals ---------------------------------------------------------- #

    def _headers(self) -> dict[str, str]:
        if not self._token:
            raise SourceError(f"{self.token_env} not found (environment, analytics/.env, "
                              f"~/.config/game-analytics-kit/.env); the {CONNECT_SKILL} "
                              "skill explains how to issue the OAuth token")
        return {"Authorization": f"OAuth {self._token}", "Accept-Encoding": "gzip"}

    def _require_app_id(self) -> str:
        if self._app is None:
            self._app = self._resolve_app()
        return self._app["id"]

    def _resolve_app(self) -> dict[str, str]:
        if not self._app_id and not self._api_key:
            raise SourceError("set sources.appmetrica.api_key (the SDK key from the game code) "
                              "or app_id in analytics.toml; `ga.py apps` lists what the token sees")
        apps = self.applications()
        if self._app_id:
            for app in apps:
                if app["id"] == self._app_id:
                    return app
            self._log(f"warning: app_id {self._app_id} is not in the token's application "
                      "list; using it anyway")
            return {"id": self._app_id, "name": "", "api_key": "", "created": "", "timezone": ""}
        matches = [app for app in apps if app["api_key"] == self._api_key]
        if len(matches) == 1:
            return matches[0]
        if not matches:
            raise SourceError(f"no app with api_key {self._api_key} under this token "
                              f"({len(apps)} visible); check `ga.py apps` or set app_id")
        raise SourceError(f"several apps share api_key {self._api_key}; set app_id in analytics.toml")

    def _download(self, table: str, params: dict[str, object], parts: int, fresh: bool,
                  dest: Path, log: Log) -> None:
        base = f"{self._host}/logs/v1/export/{table}.csv"
        headers = self._headers()
        if parts == 1:
            size = self._http.download(build_url(base, params), headers, dest, log,
                                       no_cache=fresh)
            log(f"      downloaded {human_size(size)}")
            return
        with dest.open("wb") as out:
            for number in range(parts):
                part = dest.with_name(f"{dest.stem}.part{number}{dest.suffix}")
                part_params = dict(params, parts_count=parts, part_number=number)
                try:
                    # Only the first part may ask for a rebuilt report; the others
                    # have to read the very same prepared one.
                    size = self._http.download(build_url(base, part_params), headers, part, log,
                                               no_cache=fresh and number == 0)
                    log(f"      downloaded {human_size(size)} (part {number + 1}/{parts})")
                    _append_csv(part, out)
                finally:
                    part.unlink(missing_ok=True)

    def _translate(self, error: HttpError) -> SourceError:
        if error.status == 401:
            return SourceError(f"AppMetrica answered 401: the token from {self._token_origin} is "
                               f"missing, expired or lacks appmetrica:read; see the "
                               f"{CONNECT_SKILL} skill")
        if error.status == 403:
            return SourceError("AppMetrica answered 403: this token has no access to the app; "
                               "check `ga.py apps`")
        if error.status == 400:
            return RequestRejected("AppMetrica rejected the request (400): "
                                   + _one_line(error.text), error.text)
        if error.status == 0:
            return SourceError(f"AppMetrica is unreachable: {error.text}")
        return SourceError(f"AppMetrica answered HTTP {error.status}: {_one_line(error.text)}")


def export_params(app_id: str, fields: list[str], start: date, end: date,
                  skip_shards: bool) -> dict[str, object]:
    """One request per range, not per day: exports are prepared one after another."""
    params: dict[str, object] = {
        "application_id": app_id,
        "date_since": f"{start.isoformat()} 00:00:00",
        "date_until": f"{end.isoformat()} 23:59:59",
        "date_dimension": "default",
        "fields": ",".join(fields),
    }
    if skip_shards:
        # A missing shard should thin the answer, not fail the whole export.
        params["skip_unavailable_shards"] = "true"
    return params


def _app_row(app: Mapping[str, object]) -> dict[str, str]:
    return {
        "id": str(app.get("id", "")),
        "name": str(app.get("name") or ""),
        "api_key": str(app.get("api_key") or ""),
        "created": str(app.get("create_date") or "")[:10],
        "timezone": str(app.get("time_zone_name") or ""),
    }


def _append_csv(part: Path, out: BinaryIO) -> None:
    """Stream one export part into `out`, keeping only the first header line."""
    with part.open("rb") as handle:
        if out.tell() > 0:
            handle.readline()  # every part repeats the header
        body_start = handle.tell()
        shutil.copyfileobj(handle, out, 1 << 20)
        if handle.tell() > body_start:
            handle.seek(-1, os.SEEK_END)
            if handle.read(1) != b"\n":
                out.write(b"\n")  # the next part must start on its own line


def _one_line(text: str) -> str:
    return " ".join(text.split())[:300]
