-- Sync state per source table: loaded days, gaps, fresh window, last load
-- missing_days = days between the first and the last loaded day that were never loaded.
SELECT
    source,
    table_name,
    COUNT(*)                                                    AS days_loaded,
    MIN(day)                                                    AS first_day,
    MAX(day)                                                    AS last_day,
    CAST(julianday(MAX(day)) - julianday(MIN(day)) + 1 AS INTEGER) - COUNT(*)
                                                                AS missing_days,
    SUM(rows)                                                   AS rows_total,
    SUM(is_final = 0)                                           AS days_in_fresh_window,
    SUM(rows = 0)                                               AS empty_days,
    MAX(loaded_at)                                              AS last_loaded_at
FROM sync_log
GROUP BY source, table_name
ORDER BY source, table_name;
