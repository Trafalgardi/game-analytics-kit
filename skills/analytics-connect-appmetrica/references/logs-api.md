# AppMetrica Logs API — contract and pitfalls

The engine (`analytics/kit/gak/sources/appmetrica.py`, `sync.py`, `http.py`) already
implements everything below. Read this to understand what a sync is doing, to diagnose a
failure, and to explain to the owner why data looks the way it does. Do not reimplement
the download by hand.

## Endpoints

Management API — resolves the numeric app id (the SDK key is not the id):

```
GET https://api.appmetrica.yandex.ru/management/v1/applications
Authorization: OAuth <token>
→ applications[]: id, name, api_key, create_date, time_zone_name, ...
```

Logs API — raw rows of one table for one date range:

```
GET https://api.appmetrica.yandex.ru/logs/v1/export/<table>.csv
    ?application_id=<numeric id>
    &date_since=YYYY-MM-DD HH:MM:SS
    &date_until=YYYY-MM-DD HH:MM:SS
    &date_dimension=default            # default = event time; receive = server receive time
    &fields=field_a,field_b,...
    [&parts_count=N&part_number=K]     # when a range is too big
    [&skip_unavailable_shards=true]    # thin the answer instead of failing it
Authorization: OAuth <token>
Accept-Encoding: gzip
Cache-Control: no-cache               # only for ranges that are not final yet
```

## Responses

| Status | Meaning | What the engine does |
| --- | --- | --- |
| 200 | CSV ready | streams it to a temp file, then parses |
| 202 | being prepared; body says `Progress is N%` | polls with growing interval 5→60 s, prints progress |
| 429 | three exports already queued for this app | waits `Retry-After` |
| 400 `Try to use more parts.` | range too big | retries with `parts_count` / `part_number` |
| 400, other | usually an unknown field or bad parameter | drops unknown fields, remembers them in `source_fields.rejected` |
| 401 | token missing or expired | stops with a clear message |

## Token

OAuth token of the Yandex account that sees the app, scope `appmetrica:read`. Creation
steps are in the skill body. One token serves every app of that account, so the
user-level file `~/.config/game-analytics-kit/.env` is convenient. The token is never
printed, committed, passed on a command line or stored in the database.

## Tables

Worth pulling: `events`, `sessions_starts`, `installations`, `crashes`, `errors`,
`revenue_events`, `ad_revenue_events`. Rarely useful: `clicks`, `postbacks`,
`push_tokens`, `profiles`, `deeplinks`, `ecommerce`.

| Table | One row per | You need it for |
| --- | --- | --- |
| `events` | custom (client) event | everything behavioural; parameters in `event_json` |
| `sessions_starts` | session start | sessions per device, session counts by version |
| `installations` | install (attributed) | install days, **attribution** (`publisher_name`, `tracker_name`), reinstalls |
| `crashes` | crash | stability by version / device |
| `errors` | reported error / exception | handled exceptions, their spread across devices |
| `revenue_events` | in-app purchase revenue | IAP revenue, order id, verification |
| `ad_revenue_events` | ad impression revenue | ad revenue by type, network, country |

Typical fields (names follow the API; the authoritative requested list is
`analytics/kit/gak/sources/appmetrica_fields.py`; what the API accepted or rejected is in
the `source_fields` table; the actual columns are in `PRAGMA table_info(<table>)`):

- identity: `appmetrica_device_id`, `installation_id`, `profile_id`, `session_id`;
- time: `event_datetime` (app time zone), `event_timestamp` (Unix seconds),
  `event_receive_datetime`; tables other than `events` use their own prefix
  (`install_datetime`, `crash_datetime`, `session_start_datetime`,
  `ad_revenue_datetime`, ...);
- app and device: `app_version_name`, `app_build_number`, `app_package_name`, `os_name`,
  `os_version`, `device_manufacturer`, `device_model`, `device_type`, `device_locale`,
  `country_iso_code`, `city`, `connection_type`;
- events: `event_name`, `event_json`;
- installations: `publisher_id`, `publisher_name`, `tracking_id`, `tracker_name`,
  `is_reinstallation`, `match_type`, click time;
- revenue_events: `revenue_price`, `revenue_currency`, `revenue_quantity`,
  `revenue_product_id`, `revenue_order_id`, `revenue_order_id_source`,
  `is_revenue_verified`;
- ad_revenue_events: `ad_revenue` (value), `ad_revenue_currency`, `ad_revenue_type`,
  `ad_revenue_network`, `ad_revenue_unit_id` / `_unit_name`, `ad_revenue_placement_id` /
  `_placement_name`, `ad_revenue_precision`, `ad_revenue_data_source`,
  `ad_revenue_payload`.

The engine adds `id INTEGER PRIMARY KEY`, `date` (day of the row's own event, used for
range replace) and `load_date` to every table. uint64 ids (`appmetrica_device_id`,
`session_id`) are TEXT: compare them as text, never `CAST` them to INTEGER (SQLite
integers are signed 64-bit and overflow above 2^63).

PII fields (`google_aid`, `ios_ifa`, `ios_ifv`, `windows_aid`, `android_id`,
`device_ipv6`, `operator_name`, `mcc`, `mnc`) are requested only with `--with-device-ids`.

## Game parameters

The client sends parameters as one JSON string in `event_json` — normally a flat
dictionary. The engine flattens it once into `event_params(event_id, date, load_date,
event_name, key, value_text, value_num)`, indexed on `(key, value_text)`, `(date, key)`,
`(event_id)`. Group by parameter values through `event_params`; `json_extract` over
millions of rows is slow. Nested objects stay as JSON text in `value_text`.

`profile_id` is empty unless the client sets it (`SetUserProfileID` or similar). Without
it the unit of analysis is the device: one human with two phones = two devices; a
reinstall may create a new device id depending on platform and SDK.

## Time

- `date` and `*_datetime` are in the **app's time zone** (`time_zone_name` from the
  Management API, stored in `meta`). Unix `*_timestamp` fields are time-zone free — use
  them to re-bucket into another clock.
- Google Ads reports in the ad account's time zone, AdMob in Pacific time by default,
  GA4 in the property's time zone. Day-level numbers from different tools never match
  exactly: always say which clock a number uses.
- Late delivery: events keep arriving for up to ~7 days (offline devices, batching). A
  day younger than `fresh_days` is not final and is re-pulled, but not more often than
  every `refresh_after_hours` (quota). Anything arriving later than that never shows up
  in the Logs API. Today is always incomplete.

## Quotas and throughput

- At most three exports queued per app; the fourth gets 429.
- Preparation is queued and sequential and hardly depends on the range width: a 1-day
  request waits about as long as a 7-day one. Hence 7-day chunks, and while one chunk
  downloads the engine queues the next (prefetch, two of the three slots).
- Observed: two weeks × 5 tables ≈ 13 min; 25 days × 7 tables ≈ 60 min; `errors` once
  waited 20 min at 96–98 % "preparing". Sync only the tables a question needs.
- Basic plan: about 3.25 M custom events per day; above that events are buffered and
  arrive later, and a buffer that persists for about two weeks makes AppMetrica stop
  accepting custom events. A very chatty event (per frame, per tick) can hit this.

## Pitfalls the engine already handles (do not undo them)

| Trap | How it showed up | Rule |
| --- | --- | --- |
| Per-day requests | each day waited minutes in the queue | request 7-day ranges; prefetch the next |
| Dedup by row hash | would merge genuine duplicates (two identical events in one second) | rows have no id: DELETE the chunk's days + INSERT, in one transaction |
| Re-pulling everything | quota burned, same days fetched on every run | days older than `fresh_days` are final (only `--force`); fresh days re-pulled after `refresh_after_hours` |
| Parsing from the socket | `I/O operation on closed file` | download to a temp file, then parse |
| Default Python transactions | second write failed to start its transaction | SQLite in autocommit (`isolation_level=None`), explicit `BEGIN IMMEDIATE` per chunk |
| Field drift | docs lag the API; an unknown field fails the whole export | drop unknown fields, remember them in `source_fields.rejected`; a missing column beats a failed sync |
| Two syncs, one file | `database is locked` | one writer per file; urgent table → `--db` scratch file |
| Cache on fresh days | stale report served | `Cache-Control: no-cache` for non-final ranges |

## Pitfalls for you

- The numeric `application_id` is not the SDK key — always resolve through `apps`.
- The first days of an app and the last seven days are the least reliable; say so.
- Dev builds may use a separate key or the same key — check in code, record in notes.
- A sync that "hangs" at a high percentage is usually AppMetrica preparing, not the
  engine; let it run and work on what is loaded.
