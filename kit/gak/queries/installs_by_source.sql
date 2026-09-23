-- Installed devices per day and country by source class (paid / organic / unknown)
-- One row per device: its latest installation (v_installs documents the paid/organic
-- rule). Network-side install counts are usually higher than attributed ones.
SELECT
    install_date                                 AS date,
    COALESCE(country_iso_code, '')               AS country,
    COUNT(*)                                     AS devices,
    SUM(source_class = 'paid')                   AS paid,
    SUM(source_class = 'organic')                AS organic,
    SUM(source_class = 'unknown')                AS unknown,
    SUM(install_rows > 1)                        AS reinstalled
FROM v_installs
WHERE install_date BETWEEN :since AND :until
GROUP BY install_date, country
ORDER BY install_date, devices DESC;
