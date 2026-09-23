---
name: analytics-connect-appmetrica
description: "Connects the game project to AppMetrica through the kit: finds the SDK key in the game code, walks the owner through creating a read-only OAuth token, resolves the numeric app id with 'apps', fills analytics/analytics.toml, plans and runs the first sync (long syncs in the background) and verifies the data. Holds the Logs API contract, quotas, time zones, HTTP error handling, and how to add another event source (Firebase, GameAnalytics, devtodev). Use for: 'connect AppMetrica', 'pull fresh data', 'sync failed', '401', '429', «подключи AppMetrica», «выгрузи AppMetrica», «обнови данные», «токен AppMetrica», «синк упал». Not for modeling events once data is loaded (analytics-data-model), reviewing what the game tracks (analytics-project-audit), or ad-network and store exports (analytics-import-external)."
---

# Connect AppMetrica

Commands run from the project root (conventions: the `analytics-kit` skill). Read
`analytics/notes/project.md` first — the key, app id and decisions may already be there.
Logs API details and every known pitfall: [references/logs-api.md](references/logs-api.md)
(read it before the first sync and whenever a sync behaves oddly).

## 1. Find the SDK key in the code

The SDK key (`api_key`, a UUID) ships inside the app; it is an identifier, not a secret,
and may go into `analytics.toml` and notes. Search only source and config folders (skip
`Library/`, `Temp/`, `obj/`, `build/`, `Pods/`, `node_modules/`).

| Stack | Look for |
| --- | --- |
| Unity C# | `AppMetricaConfig(`, `AppMetrica.Activate`, `YandexAppMetricaConfig`, `ActivateWithConfiguration`, an activator component or ScriptableObject with an `ApiKey` field (the key may sit in `.prefab`, `.asset`, `.unity` YAML, not in `.cs`) |
| Android Kotlin/Java | `AppMetricaConfig.newConfigBuilder(`, `YandexMetricaConfig.newConfigBuilder(`, `AppMetrica.activate(`, `YandexMetrica.activate(`; also `strings.xml`, `buildConfigField`, `local.properties`, `gradle.properties` |
| iOS Swift/ObjC | `AppMetricaConfiguration(apiKey:`, `YMMYandexMetricaConfiguration(apiKey:`, `AppMetrica.activate(with:`; also `Info.plist`, `*.xcconfig` |
| Flutter | `AppMetricaConfig(`, `AppMetrica.activate(` in `.dart`; `appmetrica_plugin` in `pubspec.yaml` |
| React Native | `AppMetrica.activate({ apiKey`, packages `@appmetrica/react-native-analytics`, `react-native-appmetrica` |
| Any | a UUID `[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}` in a file that mentions `AppMetrica` or `Metrica` |

Several keys (dev/prod, per platform, per flavor) are common: record each with the file
and the build it belongs to, and pick the production one with `apps` in step 3.

## 2. Token (owner steps)

Give the owner these steps in the report language:

1. Open https://oauth.yandex.ru/client/new and create an app: platform **Web services**,
   Redirect URI `https://oauth.yandex.ru/verification_code`, permissions **AppMetrica →
   `appmetrica:read`** (write is not needed). Use the Yandex account that sees the app.
2. Copy the **ClientID**, open
   `https://oauth.yandex.ru/authorize?response_type=token&client_id=<ClientID>`, confirm,
   and copy `access_token` from the address bar.
3. Save one line `APPMETRICA_TOKEN=<token>` in `analytics/.env` (this project only) or in
   `~/.config/game-analytics-kit/.env` (every project of this account). One token serves
   every app of the account.

Then check without revealing it: `py analytics/ga.py status` says "token found", and
`git check-ignore analytics/.env` prints the path (the file is ignored). Never print,
echo, commit or paste the token; never pass it on a command line.

## 3. Resolve the app

`py analytics/ga.py apps` → find the row whose `api_key` equals the key from step 1.
If several match or the owner has many apps, confirm the choice with the owner. Note the
numeric id, name, creation date and **time zone** (all day-level numbers use it).

## 4. Fill `analytics/analytics.toml`

- `[project]`: `name`, `report_language` (ask the owner if unsure; default `ru`), `platforms`.
- `[sources.appmetrica]`: `enabled = true`, `api_key` = the SDK key; `app_id` only if the
  key is ambiguous; `since` = first day worth having (empty = app creation date);
  keep `tables`, `chunk_days = 7`, `fresh_days = 7`, `refresh_after_hours = 12`.
- `[filters]`: ask the owner where the team's test devices are (`dev_countries`) and
  which versions were published to the store (`published_versions`). Unknown → leave
  empty and write "not confirmed" in `analytics/notes/project.md`; the data model skill
  will propose values from the data.

## 5. Measure the volume before the first big pull

Games differ by two orders of magnitude: one indie game logged 5k events a day, another
~500k (a single 7-day `events` chunk was a 1.4 GB CSV; with parameter flattening the
database grew ~6 KB per event and would have needed 30+ GB). Never start a multi-week
`events` pull in an unmeasured project:

1. Probe one complete recent day into a throwaway database:
   `py analytics/ga.py sync --db data/probe.db --tables events --since <D> --until <D>`
   (yesterday or the day before; runs in the foreground in a few minutes). Read the chunk
   line: CSV size and rows. Then delete `analytics/data/probe.db*`.
2. Decide, and write the decision into `analytics/analytics.toml` and
   `analytics/notes/project.md`:
   - **≤ 100k events/day** — pull everything, keep `flatten_params = true`.
   - **100k–500k/day** — `sample` so that the kept devices still give several hundred new
     players per compared cohort (e.g. 350 installs/day × 0.1 × 14 days ≈ 500), and
     consider `flatten_params = false`.
   - **> 500k/day** — `sample = 0.05` or lower and `flatten_params = false`.
   The sample is by device (deterministic hash), identical in every table, and fixed for a
   database: changing it later needs a new database file. The kit also refuses a chunk
   whose projected size would eat most of the free disk.
3. Sampled data: rates, shares, medians and funnels are unbiased; **absolute counts and
   revenue totals must be divided by the rate** (and labelled as estimates) before they are
   compared with any console.

## 6. First sync

1. `py analytics/ga.py sync --dry-run` — read the plan (chunks × tables).
2. `py analytics/ga.py sync --tables installations` — whole history of installs and
   attribution; cheap and needed by almost every question.
3. `py analytics/ga.py sync --tables events,sessions_starts --since <today − 28 days>` —
   the window most questions need.
4. Later, only when a question needs it: older history (the same command without
   `--since`), `crashes,errors` for stability, `revenue_events,ad_revenue_events` for money,
   or `--tables all` overnight.

Timing: preparation on AppMetrica's side dominates, not download. Two weeks × 5 tables
took ~13 min, 25 days × 7 tables ~60 min, `errors` once sat 20 min at 96–98 %
"preparing". Extrapolate from the first chunk.

- Anything longer than a few minutes runs as a **detached job**, not in your own shell
  background (that dies when your session or command ends):
  `py analytics/ga.py sync --background --tables ... --since ...` returns at once; the job
  writes `analytics/data/sync.log`. Then work (read code, model what is loaded) and follow
  it with `py analytics/ga.py sync --wait` — it streams the log and returns when the job
  ends, or after 90 seconds with exit code 3 ("still running"): call it again at once.
- **Never finish your turn while a sync you started is still running.** Wait by calling
  `sync --wait` again and again in the foreground until it reports `done` (or `failed`:
  read the log, fix, restart). Do not hand the waiting to your environment — no background
  shells, scheduled wake-ups, `sleep`, or "I will resume when it finishes": in a
  non-interactive run (`claude -p`, `codex exec`) nothing resumes you and the work stops
  half done. Between waits you may read code or query what is already loaded.
- `status` shows the running job and the days already loaded. Do not start a second sync
  into the same database (the kit refuses while a job is alive). If one table is urgent while a long sync runs, pull it into a scratch
  file with `--db analytics/data/scratch.db` and combine them in a script (`ATTACH`).
- `--with-device-ids` (advertising ids, IP, operator) only when a question needs it and
  the owner agrees.
- After each sync, if the project model has tables: `py analytics/ga.py model apply`.

## 7. Verify

- [ ] `status`: token found, app id/name/time zone in meta, every requested table has rows
      and the expected date range, fresh days listed, today marked incomplete.
- [ ] `query sync_health`: no missing days inside the window.
- [ ] `query overview` and `query dau`: plausible; compare two or three days with the
      AppMetrica web interface (same time zone) — they should agree closely.
- [ ] `query installs_by_source`: paid / organic / unknown split exists (attribution works).
- [ ] `catalog --min-count 10 --format md`: the event names match what the code sends.
- [ ] `query app_versions`: ask the owner which versions are public → `[filters]`.
- [ ] Record in `analytics/notes/project.md`: key and its file, app id, time zone, first
      synced day, tables pulled, anything odd.

## 7. Troubleshooting

| Symptom | Meaning and fix |
| --- | --- |
| 401 | Token missing, expired, revoked or without `appmetrica:read`. Owner repeats step 2 (authorize URL gives a fresh token). Check `status` finds it. |
| 403 | The token's account has no access to this app. Owner grants access in AppMetrica or uses the owning account's token. |
| 404 / app not found | Wrong numeric id or key. Rerun `apps`, fix `api_key` / `app_id`. |
| 400 `Try to use more parts.` | Day too big; the engine retries with parts. If it persists, lower `--chunk-days`. |
| 400, other text | Usually an unknown field; the engine drops it and records it in `source_fields.rejected` (`sql "SELECT * FROM source_fields"`). |
| 202 for many minutes | Report still preparing; normal. Keep working on loaded data. |
| 429 | Three exports already queued for this app (another sync, a teammate, prefetch). The engine waits `Retry-After`. Do not start parallel syncs; `--no-prefetch` if it keeps happening. |
| 5xx, network drop | Rerun the same `sync`; completed chunks are not re-requested. |
| `database is locked` | Two writers on one file. Stop one; use `--db` for the urgent table. |
| Counts lower than the web UI for recent days | Late delivery (up to 7 days); fresh days are re-pulled automatically after `refresh_after_hours`. |

## Other event sources

The engine reads sources through one interface (`Table` + `Source` with `tables()`,
`check()`, `fetch()`, `warm()`, `rejected_fields()`); sync planning, range replace,
logging and JSON flattening are generic. To add Firebase (BigQuery export), GameAnalytics,
devtodev or Amplitude, write one module plus its fields module **in the kit repository**,
register it, cover it in `selftest`, and install it with `install.py --update` — never
inside the project's `analytics/kit/`. Until it exists, load that tool's exports with
`import-csv --kind generic --table <name>`. Details and per-provider notes:
[references/other-sources.md](references/other-sources.md).
