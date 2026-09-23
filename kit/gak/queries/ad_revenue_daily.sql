-- Ad revenue per day, country, ad type and network (ad_revenue_events)
-- impressions = rows of ad_revenue_events; revenue is in ad_revenue_currency;
-- ecpm = revenue per 1000 impressions.
SELECT
    date,
    COALESCE(country_iso_code, '')               AS country,
    COALESCE(ad_revenue_type, '')                AS ad_type,
    COALESCE(ad_revenue_network, '')             AS network,
    COALESCE(ad_revenue_currency, '')            AS currency,
    COUNT(*)                                     AS impressions,
    COUNT(DISTINCT appmetrica_device_id)         AS devices,
    ROUND(SUM(ad_revenue), 4)                    AS revenue,
    ROUND(1000.0 * SUM(ad_revenue) / COUNT(*), 2) AS ecpm
FROM ad_revenue_events
WHERE date BETWEEN :since AND :until
GROUP BY 1, 2, 3, 4, 5
ORDER BY date, revenue DESC;
