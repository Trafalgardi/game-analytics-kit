"""HTTP for sources: stdlib urllib, bodies streamed to disk, patient with slow servers.

Why it looks like this (each point cost real time once):
- A body is streamed to a file in chunks and parsed afterwards. Parsing straight
  off the socket broke ("I/O operation on closed file") and would keep the
  connection open for as long as SQLite takes to insert.
- 202 means "the export is being prepared": poll with growing pauses (5 -> 60 s)
  and print the progress the server reports. Only the first request may ask for
  a rebuilt answer (Cache-Control: no-cache); a poll that did would restart the
  very preparation it is waiting for.
- 429 means the server's queue is full: wait Retry-After (seconds or HTTP date).
- Network errors and 5xx answers are retried with backoff; a download cut off
  halfway starts over and overwrites the partial file.
- urllib does not decode gzip: Content-Encoding: gzip is unpacked here.
The opener and sleep are injectable so selftest drives every branch offline.
"""

from __future__ import annotations

import gzip
import http.client
import json
import re
import shutil
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

from . import __version__

USER_AGENT = f"game-analytics-kit/{__version__}"
POLL_INTERVALS = (5, 10, 20, 30, 60)   # 202: check often at first, then back off
QUOTA_WAIT_SEC = 60                    # 429 without a usable Retry-After
RETRY_BACKOFF = (5, 15, 30, 60)        # network errors and 5xx
RETRY_STATUSES = frozenset({500, 502, 503, 504})
CHUNK_BYTES = 1 << 20
ERROR_BODY_BYTES = 64 * 1024
PROGRESS_RE = re.compile(r"(\d{1,3})\s*%")
TRANSIENT_ERRORS = (OSError, http.client.HTTPException, EOFError)

Log = Callable[[str], None]


class Response(Protocol):
    """What an opener returns: urllib's response or HTTPError, or a test fake."""

    status: int
    headers: Any  # needs .get(name)

    def read(self, size: int = -1) -> bytes: ...

    def close(self) -> None: ...


Opener = Callable[[urllib.request.Request, float], Response]


class HttpError(Exception):
    """A final, non-retryable answer (status 0 = the network itself failed)."""

    def __init__(self, status: int, text: str, retry_after: int = 0):
        super().__init__(f"HTTP {status}: {text[:300]}" if status else text)
        self.status = status
        self.text = text
        self.retry_after = retry_after


@dataclass(frozen=True)
class Answer:
    status: int
    text: str = ""
    retry_after: int = 0
    size: int = 0


def urlopen(request: urllib.request.Request, timeout: float) -> Response:
    """Default opener: non-2xx answers come back as responses, not exceptions."""
    try:
        return urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as error:
        return error  # carries status, headers and body like a response


def build_url(base: str, params: Mapping[str, object]) -> str:
    return base + ("?" + urllib.parse.urlencode(params) if params else "")


def parse_retry_after(value: str | None) -> int:
    """Seconds to wait, from either form of the Retry-After header."""
    if not value:
        return 0
    value = value.strip()
    if value.isdigit():
        return int(value)
    try:
        retry_at = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return 0
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=timezone.utc)
    return max(0, int((retry_at - datetime.now(tz=retry_at.tzinfo)).total_seconds()))


def human_size(size: float) -> str:
    for unit in ("B", "KB", "MB"):
        if size < 1024:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} GB"


class Http:
    """Stateless client: every call opens its own connection, so threads may share it."""

    def __init__(self, *, timeout: float = 180.0, opener: Opener | None = None,
                 sleep: Callable[[float], None] = time.sleep, retries: int = 4):
        self._timeout = timeout
        self._opener = opener or urlopen
        self._sleep = sleep
        self._retries = retries

    def get_json(self, url: str, headers: Mapping[str, str], log: Log) -> Any:
        answer = self._call(url, headers, None, log)
        try:
            return json.loads(answer.text)
        except ValueError:
            raise HttpError(answer.status, "answer is not JSON: " + answer.text[:200]) from None

    def download(self, url: str, headers: Mapping[str, str], dest: Path, log: Log,
                 *, no_cache: bool = False) -> int:
        """Stream a 200 body into `dest`, waiting through 202/429; returns its size."""
        return self._call(url, headers, dest, log, no_cache=no_cache).size

    def touch(self, url: str, headers: Mapping[str, str]) -> int:
        """One request, body ignored: enough to make a server start preparing."""
        response = self._opener(urllib.request.Request(url, headers=_with_agent(headers)),
                                self._timeout)
        try:
            return _status(response)
        finally:
            response.close()

    def _call(self, url: str, headers: Mapping[str, str], dest: Path | None, log: Log,
              *, no_cache: bool = False) -> Answer:
        waited = 0.0
        polls = 0
        failures = 0
        while True:
            sent = _with_agent(headers)
            if no_cache:
                sent["Cache-Control"] = "no-cache"
            answer, problem = self._attempt(url, sent, dest)
            if problem:
                failures += 1
                if failures > self._retries:
                    raise HttpError(answer.status if answer else 0,
                                    f"{problem}; gave up after {self._retries} retries")
                wait = RETRY_BACKOFF[min(failures - 1, len(RETRY_BACKOFF) - 1)]
                log(f"      {problem}, retry {failures}/{self._retries} in {wait}s")
                self._sleep(wait)
                continue
            failures = 0
            if answer.status == 200:
                return answer
            if answer.status == 202:
                no_cache = False  # a poll must never restart the preparation it waits for
                match = PROGRESS_RE.search(answer.text)
                progress = f"{match.group(1)}%" if match else "queued"
                wait = POLL_INTERVALS[min(polls, len(POLL_INTERVALS) - 1)]
                polls += 1
                log(f"      preparing {progress} - waiting {waited:.0f}s so far, "
                    f"next check in {wait}s")
                self._sleep(wait)
                waited += wait
                continue
            if answer.status == 429:
                wait = answer.retry_after or QUOTA_WAIT_SEC
                log(f"      queue is full (429), waiting {wait}s as Retry-After asks")
                self._sleep(wait)
                waited += wait
                continue
            raise HttpError(answer.status, answer.text, answer.retry_after)

    def _attempt(self, url: str, headers: dict[str, str],
                 dest: Path | None) -> tuple[Answer | None, str]:
        """One exchange; returns (answer, "") or (answer or None, retryable problem)."""
        try:
            answer = self._exchange(url, headers, dest)
        except TRANSIENT_ERRORS as error:
            reason = getattr(error, "reason", error)
            if isinstance(reason, ssl.SSLCertVerificationError):
                raise HttpError(0, f"TLS certificate check failed: {reason}") from None
            return None, f"network error ({type(error).__name__}: {error})"
        if answer.status in RETRY_STATUSES:
            return answer, f"server error {answer.status}"
        return answer, ""

    def _exchange(self, url: str, headers: dict[str, str], dest: Path | None) -> Answer:
        response = self._opener(urllib.request.Request(url, headers=headers), self._timeout)
        try:
            status = _status(response)
            body = _decoded(response)
            if status == 200 and dest is not None:
                with dest.open("wb") as handle:
                    shutil.copyfileobj(body, handle, CHUNK_BYTES)
                return Answer(status, size=dest.stat().st_size)
            raw = body.read() if status == 200 else body.read(ERROR_BODY_BYTES)
            retry_after = parse_retry_after(_header(response, "Retry-After"))
            return Answer(status, raw.decode("utf-8", "replace"), retry_after)
        finally:
            response.close()


def _with_agent(headers: Mapping[str, str]) -> dict[str, str]:
    return {"User-Agent": USER_AGENT, **headers}


def _status(response: Response) -> int:
    return int(getattr(response, "status", None) or getattr(response, "code", 0) or 0)


def _header(response: Response, name: str) -> str | None:
    headers = getattr(response, "headers", None)
    return headers.get(name) if headers is not None else None


def _decoded(response: Response) -> Any:
    """The body as a readable stream, gunzipped when the server compressed it."""
    if "gzip" in (_header(response, "Content-Encoding") or "").lower():
        return gzip.GzipFile(fileobj=response, mode="rb")
    return response
