-- Event volume and reach per event name
SELECT
    event_name,
    COUNT(*)                                                    AS events,
    COUNT(DISTINCT appmetrica_device_id)                        AS devices,
    ROUND(1.0 * COUNT(*) / NULLIF(COUNT(DISTINCT appmetrica_device_id), 0), 2)
                                                                AS per_device,
    MIN(date)                                                   AS first_date,
    MAX(date)                                                   AS last_date
FROM events
WHERE date BETWEEN :since AND :until
GROUP BY event_name
ORDER BY events DESC;
