# Project model

SQL that turns the raw source tables into this project's vocabulary: typed event views,
per-device tables, sessions, cohorts. Files run in name order with `py analytics/ga.py model apply`,
so number them: `010_v_events.sql`, `020_devices.sql`, `030_sessions.sql`...

Start with `py analytics/ga.py model scaffold`, then edit. Keep definitions here, not in queries:
a filter or a cohort rule that lives in one place cannot drift between reports.
