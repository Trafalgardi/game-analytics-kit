-- Core schema of game-analytics-kit: static tables and generic views.
--
-- Source tables (events, sessions_starts, installations, crashes, errors,
-- revenue_events, ad_revenue_events) are created by store.ensure_schema from the
-- source field lists before this file runs. Everything here touches core
-- columns only, never game parameters: those belong to the project model
-- (analytics/model/*.sql, e.g. v_events).
-- Views are dropped and recreated whenever the schema is ensured, so a kit
-- update reaches existing databases.

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- One row per (source, table, day). is_final marks a day older than the
-- late-delivery window (fresh_days): the source will not add to it, so it is
-- never requested again unless sync runs with --force.
CREATE TABLE IF NOT EXISTS sync_log (
    source     TEXT NOT NULL,
    table_name TEXT NOT NULL,
    day        TEXT NOT NULL,
    loaded_at  TEXT NOT NULL,
    rows       INTEGER NOT NULL,
    is_final   INTEGER NOT NULL,
    PRIMARY KEY (source, table_name, day)
);

-- Per source table: the field list that last worked and the fields the remote
-- rejected. "rejected" is what drives the next request: reusing the accepted
-- list instead would silently re-enable advertising ids after a single
-- --with-device-ids run.
CREATE TABLE IF NOT EXISTS source_fields (
    source     TEXT NOT NULL,
    table_name TEXT NOT NULL,
    accepted   TEXT NOT NULL DEFAULT '',
    rejected   TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    PRIMARY KEY (source, table_name)
);

-- Flattened events.event_json: one row per event parameter. event_id points to
-- events.id, which changes whenever that day is reloaded - join, never store it.
-- Costs ~140 bytes per parameter (row + three indexes), which is most of the
-- database for a game with 20-30 parameters per event; sync with
-- flatten_params = false leaves it empty (catalog and scaffold then read
-- event_json, v_event_catalog is empty, generic queries never use it).
CREATE TABLE IF NOT EXISTS event_params (
    event_id   INTEGER NOT NULL,
    date       TEXT,
    load_date  TEXT,
    event_name TEXT,
    key        TEXT NOT NULL,
    value_text TEXT,
    value_num  REAL
);
CREATE INDEX IF NOT EXISTS idx_event_params_key   ON event_params(key, value_text);
CREATE INDEX IF NOT EXISTS idx_event_params_date  ON event_params(date, key);
CREATE INDEX IF NOT EXISTS idx_event_params_event ON event_params(event_id);

-- Console exports (Google Ads, AdMob, GA4, Play Console) loaded by
-- `ga.py import-csv` into ext_<name> tables; preamble keeps the report title
-- and date range lines some consoles put above the header.
CREATE TABLE IF NOT EXISTS imports (
    id          INTEGER PRIMARY KEY,
    file        TEXT NOT NULL,
    kind        TEXT NOT NULL,
    table_name  TEXT NOT NULL,
    rows        INTEGER NOT NULL,
    imported_at TEXT NOT NULL,
    sha256      TEXT NOT NULL,
    preamble    TEXT
);

-- Event name x parameter key: how often, on how many devices, how varied,
-- how numeric. `ga.py catalog` adds sample values and a date filter.
DROP VIEW IF EXISTS v_event_catalog;
CREATE VIEW v_event_catalog AS
SELECT
    p.event_name,
    p.key,
    COUNT(*)                                          AS occurrences,
    COUNT(DISTINCT e.appmetrica_device_id)            AS devices,
    COUNT(DISTINCT p.value_text)                      AS distinct_values,
    ROUND(1.0 * SUM(p.value_num IS NOT NULL)
          / NULLIF(SUM(p.value_text IS NOT NULL), 0), 3) AS numeric_share,
    MIN(p.value_text)                                 AS min_text,
    MAX(p.value_text)                                 AS max_text,
    MIN(p.date)                                       AS first_date,
    MAX(p.date)                                       AS last_date
FROM event_params p
JOIN events e ON e.id = p.event_id
GROUP BY p.event_name, p.key;

-- Daily active devices. The last loaded day is usually incomplete.
DROP VIEW IF EXISTS v_dau;
CREATE VIEW v_dau AS
SELECT
    date,
    COUNT(DISTINCT appmetrica_device_id) AS dau,
    COUNT(*)                             AS events,
    ROUND(1.0 * COUNT(*) / NULLIF(COUNT(DISTINCT appmetrica_device_id), 0), 1)
                                         AS events_per_device
FROM events
GROUP BY date;

-- First event of every device in the loaded window: day, time, version and
-- country the device started with. Cohorts are built from this, not from
-- installation rows (a reinstall is a new installation, the same device).
DROP VIEW IF EXISTS v_device_first_seen;
CREATE VIEW v_device_first_seen AS
WITH ranked AS (
    SELECT
        appmetrica_device_id AS device_id,
        date,
        event_datetime,
        event_timestamp,
        app_version_name,
        country_iso_code,
        ROW_NUMBER() OVER (PARTITION BY appmetrica_device_id
                           ORDER BY event_timestamp, id) AS rn
    FROM events
    WHERE appmetrica_device_id IS NOT NULL AND appmetrica_device_id <> ''
),
activity AS (
    SELECT
        appmetrica_device_id AS device_id,
        MAX(date)            AS last_date,
        COUNT(DISTINCT date) AS active_days,
        COUNT(*)             AS events
    FROM events
    WHERE appmetrica_device_id IS NOT NULL AND appmetrica_device_id <> ''
    GROUP BY appmetrica_device_id
)
SELECT
    r.device_id,
    r.date             AS first_date,
    r.event_datetime   AS first_event_datetime,
    r.event_timestamp  AS first_event_timestamp,
    r.app_version_name AS first_version,
    r.country_iso_code AS first_country,
    a.last_date,
    a.active_days,
    a.events
FROM ranked r
JOIN activity a ON a.device_id = r.device_id
WHERE r.rn = 1;

-- Latest installation row per device, with its attribution.
-- Core views are recreated whenever the schema is ensured (every sync), so a
-- project that knows better writes its own rule into a model view (e.g.
-- model/040_installs.sql) instead of redefining this one.
-- source_class rule:
--   'paid'    publisher_name is set and is not a store or organic marker
--             ('Google Play', 'App Store', 'Google Search', 'Organic',
--             compared case-insensitively) - e.g. 'Google Ads';
--   'organic' otherwise, when tracker_name is 'Google Play', 'Google Search'
--             or 'App Store';
--   'unknown' everything else: unattributed installs (in paid periods mostly
--             paid-adjacent, so never count them as organic).
DROP VIEW IF EXISTS v_installs;
CREATE VIEW v_installs AS
WITH ranked AS (
    SELECT
        i.*,
        COUNT(*) OVER (PARTITION BY appmetrica_device_id) AS install_rows,
        ROW_NUMBER() OVER (PARTITION BY appmetrica_device_id
                           ORDER BY install_datetime DESC, id DESC) AS rn
    FROM installations i
    WHERE appmetrica_device_id IS NOT NULL AND appmetrica_device_id <> ''
)
SELECT
    appmetrica_device_id AS device_id,
    date                 AS install_date,
    install_datetime,
    install_rows,
    is_reinstallation,
    match_type,
    publisher_id,
    publisher_name,
    tracking_id,
    tracker_name,
    country_iso_code,
    app_version_name,
    device_model,
    CASE
        WHEN TRIM(COALESCE(publisher_name, '')) <> ''
             AND LOWER(TRIM(publisher_name)) NOT IN
                 ('google play', 'app store', 'google search', 'organic')
            THEN 'paid'
        WHEN tracker_name IN ('Google Play', 'Google Search', 'App Store')
            THEN 'organic'
        ELSE 'unknown'
    END AS source_class
FROM ranked
WHERE rn = 1;
