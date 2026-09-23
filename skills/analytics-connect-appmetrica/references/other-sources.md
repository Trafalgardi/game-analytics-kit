# Adding another event source

Read this when the project sends its events somewhere other than AppMetrica (Firebase /
GA4 with the BigQuery export, GameAnalytics, devtodev, Amplitude, ByteBrew) and the
question cannot be answered from AppMetrica alone.

## Where the code goes

Sources are part of the engine, so they are written **in the kit repository**, not in the
project's `analytics/kit/` (that copy is replaced on every update):

```
<kit repo>/kit/gak/sources/<name>.py          Source implementation
<kit repo>/kit/gak/sources/<name>_fields.py   per-table field lists and column types
<kit repo>/kit/gak/sources/__init__.py        register name -> Source class
<kit repo>/kit/selftest.py                    synthetic rows of the same shape, offline
```

Then install into the project: `py <kit repo>/install.py <project root> --update`, add a
`[sources.<name>]` block to `analytics/analytics.toml`, put the secret in
`analytics/.env`, and run `py analytics/ga.py sync --source <name> --dry-run`.

If you cannot change the kit (no access, owner said no), do not patch the project copy.
Load the tool's own exports as CSV with
`py analytics/ga.py import-csv <file> --kind generic --table <name>` and say in the
report that the data came from a manual export (range, filters, time zone).

## The interface

```python
class Table:                 # dataclass
    name: str                # table name in SQLite, e.g. "events"
    fields: list[str]        # requested fields, in order
    date_field: str          # field whose date() fills the `date` column (event day)
    json_field: str | None   # field flattened into event_params, e.g. "event_json"
    default: bool            # part of the default sync set
    pii_fields: list[str]    # only requested with --with-device-ids

class Source:
    name: str
    def tables(self) -> list[Table]
    def check(self) -> str   # "who am I connected to" line, for status/apps
    def fetch(self, table, fields, start, end, dest, log) -> Path   # CSV with header
    def warm(self, table, fields, start, end) -> None               # optional prefetch
    def rejected_fields(self, error_text, fields) -> list[str]      # field drift
```

Everything else is generic: chunk planning, fresh window and refresh-after, replace by
date range, `sync_log`, `source_fields`, flattening `json_field` into `event_params`.

Requirements for a new source:

- `fetch` writes a complete CSV with a header to `dest` (a temp file), never streams rows
  into the database.
- Map the provider's device identifier to a column the model can use as the device, and
  keep uint64-like ids as text.
- Put the event's day in the app's or provider's time zone into `date_field`, and record
  that time zone in `meta` through `check()` or the source's setup so reports can state it.
- Parameters must end up as a flat JSON dictionary in `json_field` so `event_params` and
  `catalog` work unchanged.
- PII (advertising ids, IP) goes into `pii_fields`.
- Handle the provider's "not ready yet" and rate-limit answers with waits, not failures.

## Provider notes

- **Firebase / GA4** — raw events are available only through the BigQuery export
  (daily `events_YYYYMMDD` tables, intraday tables while the day is open). Parameters are
  a repeated `event_params` record (`key` + `value.string_value / int_value /
  float_value / double_value`): flatten it to a flat JSON dictionary. `user_pseudo_id` is
  the device-level id; `event_timestamp` is in microseconds UTC; `event_date` is in the
  property's time zone. Querying BigQuery costs money per byte scanned — select only the
  needed columns and date partitions.
- **GameAnalytics, devtodev, Amplitude, ByteBrew** — each offers a raw-data export or
  API with its own limits and plan requirements. Check the provider's current
  documentation for: authentication, how to request a date range, whether exports are
  asynchronous (poll like AppMetrica's 202), the time zone of timestamps, and the
  parameter format. Record what you learn in the kit repository docs, not only in this
  project.

When two providers receive the same events, AppMetrica stays the primary source unless
the owner decides otherwise; use the second one for reconciliation (counts per day per
event) and say which one a number comes from.
