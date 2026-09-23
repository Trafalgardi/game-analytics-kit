-- D1 / D3 / D7 retention by first-seen day (percent of devices; n = devices)
-- A device is retained on day N when it has any event N calendar days after its first
-- day. A rate stays empty until day N is complete, i.e. earlier than the last loaded
-- day (usually partial). First-seen = first event in the loaded window.
WITH last AS (
    SELECT MAX(date) AS last_date FROM events
),
cohort AS (
    SELECT appmetrica_device_id AS device_id, MIN(date) AS first_date
    FROM events
    WHERE appmetrica_device_id IS NOT NULL AND appmetrica_device_id <> ''
    GROUP BY appmetrica_device_id
),
active AS (
    SELECT DISTINCT appmetrica_device_id AS device_id, date FROM events
),
returns AS (
    SELECT
        c.first_date,
        c.device_id,
        MAX(julianday(a.date) - julianday(c.first_date) = 1) AS d1,
        MAX(julianday(a.date) - julianday(c.first_date) = 3) AS d3,
        MAX(julianday(a.date) - julianday(c.first_date) = 7) AS d7
    FROM cohort c
    JOIN active a ON a.device_id = c.device_id
    WHERE c.first_date BETWEEN :since AND :until
    GROUP BY c.first_date, c.device_id
)
SELECT
    r.first_date AS cohort,
    COUNT(*)     AS devices,
    CASE WHEN julianday(l.last_date) - julianday(r.first_date) > 1
         THEN ROUND(100.0 * SUM(r.d1) / COUNT(*), 1) END AS d1_pct,
    CASE WHEN julianday(l.last_date) - julianday(r.first_date) > 3
         THEN ROUND(100.0 * SUM(r.d3) / COUNT(*), 1) END AS d3_pct,
    CASE WHEN julianday(l.last_date) - julianday(r.first_date) > 7
         THEN ROUND(100.0 * SUM(r.d7) / COUNT(*), 1) END AS d7_pct
FROM returns r
CROSS JOIN last l
GROUP BY r.first_date
ORDER BY r.first_date;
