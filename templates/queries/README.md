# Project queries

One `.sql` file per question. The first line is a comment with the title:

    -- D1 retention by first-seen day and country tier

Parameters are written as `:since`, `:until` and passed with `--param since=2026-09-01`.
Run with `py analytics/ga.py query <name>`; `py analytics/ga.py query list` shows these together
with the kit's generic queries.
