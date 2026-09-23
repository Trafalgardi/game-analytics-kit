-- DAU, events per device and 7-day active devices (WAU) per day
WITH daily AS (
    SELECT DISTINCT date, appmetrica_device_id AS device_id
    FROM events
    WHERE date BETWEEN date(:since, '-6 days') AND :until
),
counts AS (
    SELECT date, COUNT(*) AS events
    FROM events
    WHERE date BETWEEN :since AND :until
    GROUP BY date
),
active AS (
    SELECT date, COUNT(*) AS dau FROM daily GROUP BY date
)
SELECT
    c.date,
    a.dau,
    c.events,
    ROUND(1.0 * c.events / NULLIF(a.dau, 0), 1)                 AS events_per_device,
    (SELECT COUNT(DISTINCT w.device_id) FROM daily w
      WHERE w.date BETWEEN date(c.date, '-6 days') AND c.date)  AS wau
FROM counts c
JOIN active a ON a.date = c.date
ORDER BY c.date;
