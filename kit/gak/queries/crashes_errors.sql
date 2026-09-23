-- Crash and error groups with affected devices and a sample text
SELECT * FROM (
    SELECT
        'crash'                                  AS kind,
        COALESCE(crash_group_id, '(none)')       AS group_id,
        COUNT(*)                                 AS occurrences,
        COUNT(DISTINCT appmetrica_device_id)     AS devices,
        MIN(date)                                AS first_date,
        MAX(date)                                AS last_date,
        SUBSTR(REPLACE(REPLACE(COALESCE(MAX(crash), ''), CHAR(10), ' '), CHAR(13), ' '), 1, 160)
                                                 AS sample
    FROM crashes
    WHERE date BETWEEN :since AND :until
    GROUP BY 2
    UNION ALL
    SELECT
        'error',
        COALESCE(error_id, '(none)'),
        COUNT(*),
        COUNT(DISTINCT appmetrica_device_id),
        MIN(date),
        MAX(date),
        SUBSTR(REPLACE(REPLACE(COALESCE(MAX(error), ''), CHAR(10), ' '), CHAR(13), ' '), 1, 160)
    FROM errors
    WHERE date BETWEEN :since AND :until
    GROUP BY 2
)
ORDER BY occurrences DESC
LIMIT :limit;
