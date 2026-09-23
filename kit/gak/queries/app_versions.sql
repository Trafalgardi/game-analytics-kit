-- Devices and events per app version and build
SELECT
    COALESCE(app_version_name, '(none)')         AS app_version,
    app_build_number,
    COUNT(DISTINCT appmetrica_device_id)         AS devices,
    COUNT(*)                                     AS events,
    MIN(date)                                    AS first_date,
    MAX(date)                                    AS last_date
FROM events
WHERE date BETWEEN :since AND :until
GROUP BY 1, 2
ORDER BY devices DESC;
