-- Daily overview: active devices, new devices, events, sessions, installs
-- new_devices = devices whose first event in the loaded window is on that day.
-- The last loaded day is usually incomplete.
WITH days AS (
    SELECT date, COUNT(DISTINCT appmetrica_device_id) AS dau, COUNT(*) AS events
    FROM events
    WHERE date BETWEEN :since AND :until
    GROUP BY date
),
first_seen AS (
    SELECT MIN(date) AS date FROM events GROUP BY appmetrica_device_id
),
new_devices AS (
    SELECT date, COUNT(*) AS new_devices FROM first_seen
    WHERE date BETWEEN :since AND :until GROUP BY date
),
sessions AS (
    SELECT date, COUNT(*) AS sessions FROM sessions_starts
    WHERE date BETWEEN :since AND :until GROUP BY date
),
installs AS (
    SELECT date, COUNT(*) AS installs FROM installations
    WHERE date BETWEEN :since AND :until GROUP BY date
)
SELECT
    d.date,
    d.dau,
    COALESCE(n.new_devices, 0) AS new_devices,
    d.events,
    COALESCE(s.sessions, 0)    AS sessions,
    COALESCE(i.installs, 0)    AS installs
FROM days d
LEFT JOIN new_devices n ON n.date = d.date
LEFT JOIN sessions s    ON s.date = d.date
LEFT JOIN installs i    ON i.date = d.date
ORDER BY d.date;
