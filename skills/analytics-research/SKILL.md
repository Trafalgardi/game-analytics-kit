---
name: analytics-research
description: "Answers a product question — or runs a full review of the game over a period — end to end from the local analytics database: restates the request and the decision it serves, refreshes only the data it needs, starts from the engine's standard tables (key metrics by build version, drop-off by loading/FTUE steps and by 30 s of play, core actions by their number in the session, leaving after negative events), builds per-device tables, reads raw event sequences, tests hypotheses by country, source and build, verifies key numbers with an independent pass, and finishes with a versioned report in the fixed seven-block skeleton, a findings entry and a short chat summary. Playbooks: full review, why players leave, did a build change engagement, does paid UA pay back, first-session loss, ad monetization health, did organic change. Use for 'full analysis of the game', 'why don't players stay', 'did the update help', 'metrics report', «полный анализ игры», «полный разбор», «почему игроки уходят», «ретеншн», «закупка окупается?», «отчёт по метрикам», «что изменилось в новом билде», «где теряем игроков». Not for first setup (analytics-connect-appmetrica, analytics-data-model), code tracking review (analytics-project-audit), or formatting only (analytics-report)."
---

# Research a product question

Commands run from the project root (conventions: the `analytics-kit` skill). Traps that
made real reports wrong — read before the first query:
[references/pitfalls.md](references/pitfalls.md). Step-by-step playbooks, including the
default set of a **full review**: [references/question-playbooks.md](references/question-playbooks.md)
— read the matching one at step 1.

## Workflow

1. **Frame.** Restate the request and the decision it serves; list what would change the
   decision; split it into sub-questions (they become the report's short answers). Decide
   the kind:
   - «полный анализ / полный разбор / сделай анализ игры за период», "full review" →
     **full** review, playbook 0: every block, the default set of tables;
   - one question → **question** report: blocks 1, 6, 7 and those of 2–5 it needs.
   The report's title is the request: «<Game> <version>, <period>: <what was asked>», game name
   first; the slug comes from it (`full-review-2026-09-08-21`, `first-session-loss`). Decide the
   **population** now — new players by the project's rule (notes) as a `--players` view or
   SELECT — and use the same one for every table of the report. Write all this into the plan.
   *Checkpoint:* if an ambiguity would change the answer (which build is "new", which
   countries or period count, what "stay" means), ask the owner now; for "the last two weeks"
   take the last 14 complete days and say so.

2. **Read what is known.** `analytics/notes/project.md` (filters, event meaning, time
   zone, attribution, who counts as a new player) and `analytics/notes/findings.md`. Reuse
   definitions and filters; do not re-argue an owner decision recorded there — if new data
   contradicts it, present the evidence and let the owner decide.

3. **Data.** `py analytics/ga.py status`. List the tables and days the question needs
   (behaviour: `events`, `sessions_starts`, `installations`; stability: `crashes`,
   `errors`; money: `ad_revenue_events`, `revenue_events`). Size the pull:
   - cohorts: how many devices per compared group will there be (`sql` on `v_players` by
     first day)? With 40–70 per group only several-fold differences are real — widen
     the window or say the question cannot be settled yet;
   - D1 needs the next day complete, D7 seven more days; the last ~7 days are preliminary;
   - time: preparation dominates (two weeks × 5 tables ≈ 13 min).
   Sync only what is missing (`sync --tables ... --since ...`). A long pull runs as a
   detached job: `sync --background ...`, analyse what is already loaded meanwhile, and
   follow it with `sync --wait` (exit 3 after 90 s = still running, call it again at once,
   in the foreground). Never end your turn while your sync is running and never hand the
   waiting to your environment (background shells, scheduled wake-ups). After a sync: `py analytics/ga.py model apply`.

4. **Open a report version** early:
   `py analytics/ga.py report new <slug> --kind full|question --title "<the request>"`
   (same topic → same slug; changes → `--from vK`). Everything scratch lives in its
   `work/`: `plan.md`, scripts, CSVs, `claims.md`.

5. **Standard tables first.** They are the same in every report and computed by the engine:
   ```
   py analytics/ga.py keymetrics --since D --until D --players P
   py analytics/ga.py dropoff    --since D --until D --players P --steps <steps view>
   py analytics/ga.py ordinals   --since D --until D --players P --events <core actions>
   py analytics/ga.py leaving    --since D --until D --players P --events <negative events>,<a neutral event> --pause <pause events or view> --ignore <heartbeats>
   ```
   A full review has all four (ordinals and leaving in a question report when it is about the
   core loop or churn).
   Read them as text, then write them into the report (`--format html --out .../assets/...`,
   see analytics-report). The population (`--players`, e.g. only devices that are new by the
   project's rule) and the steps view (`device_id, step_no, step_name` [, `sec` = how long the
   step took]: every loading step, then every tutorial step, then the first core action — as
   fine-grained as the events allow, `step_name` in the report language because it is printed
   in the report) come from
   the model — if the model lacks them, add them there (analytics-data-model, modeling
   guide §11–15), not in a scratch script.

6. **Per-device table.** One script, `work/devices.py`: Python stdlib `sqlite3` opened
   read-only (`sqlite3.connect('file:analytics/data/analytics.db?mode=ro', uri=True)`;
   path from `[database].path`), starting from the model (`v_players`, `device_metrics`,
   `sessions`), adding the question's metrics per device, writing `work/devices.csv`. Use
   pandas only if it is already installed. Answer every sub-question from this table.
   Logic you will need again belongs in the model (`analytics-data-model`).

7. **Raw sequences.** Before trusting any aggregate, print the ordered events of 5–10
   devices across segments (paid/organic, retained/churned, old/new build). Write what
   you see in `work/plan.md`. This is where wrong assumptions surface.

8. **Hypotheses.** Number them `H1`, `H2`… in `work/plan.md`: the claim, the numbers it rests
   on, the slice that would refute it, the test (metric and threshold), the confidence. Always
   split by country tier and source before blaming a build or a channel; compare only
   complete days, same geo + same source. Medians and distributions next to means; n next
   to every rate. Each recommendation you will make must follow from one of them.

9. **Verification pass.** List the 5–10 numbers the conclusions rest on in
   `work/claims.md`: claim, number, n, definition, filters, how computed, **where it is shown**
   (the section id of the table or chart). Recompute them independently:
   - if your environment can run a sub-agent, give it the database path, the
     definitions and filters from the notes and the claims **with the numbers removed**,
     and ask it to compute them from raw tables without your scripts;
   - otherwise write `work/verify.py` from the definitions, not from the first script,
     using a different path (raw `events` instead of model tables, Python instead of SQL).
   Record a verdict per claim: confirmed / corrected (old → new, cause) / unverifiable.
   *Checkpoint:* any mismatch beyond rounding is explained before writing.

10. **Stop and ask** when: an ambiguity would change the decision; external data is
    missing (spend, console numbers) — request it with exact console paths from the
    `analytics-import-external` skill and continue with what is possible, marking the gap;
    the result contradicts a recorded owner decision; the sample cannot support an answer.

11. **Report** through the `analytics-report` skill, in the report language, in the fixed
    skeleton: 1 summary (key metrics by version + short answers) → 2 product → 3 revenue →
    4 technical → 5 countries → 6 hypotheses → 7 recommendations → data requests → method.
    Facts in tables and charts, interpretation marked as such, every number of blocks 1, 6, 7
    shown above.

12. **Log.** Add a dated entry at the top of `analytics/notes/findings.md` in the format
    its header describes: date, question, the answer in two or three sentences, the
    numbers it rests on with n, the hypotheses and their status, the report
    (`reports/<slug>/vNNN`, and the link if published); add open data requests and owner
    decisions. Put durable facts (a new filter, a definition, a tracking defect) into
    `analytics/notes/project.md`.

13. **Chat summary** (owner's language, 3–8 lines): the direct answers with numbers and
    n, the one most important recommendation and its hypothesis, what data is still needed,
    the report link and local `report.html` path.

## Reading numbers

- `status` says whether the database is a device sample (`sample: 10% of devices`). With a
  sample, rates, medians and per-device distributions stand as they are; absolute counts,
  installs and revenue totals are divided by the rate, and the report marks them «≈ … оценка»
  next to the sample number (the standard tables print both). Cohorts smaller than
  ~50 devices after sampling are not worth splitting further.
- The device is the unit; dev devices are already excluded in `v_players` — never mix
  in `devices` without `is_dev = 0`.
- Cohorts by first event. Today and the last ~7 days are incomplete. State the clock.
- A 5–7 pp difference on 40–70 devices is noise; call an effect only when it is several-fold
  or repeats in independent slices.
- Session span is not play time; heartbeat builds look longer; ad "failures" may be
  impressions; an SDK session may break on every backgrounding (an interstitial included) —
  check the notes for the project's session unit. See the pitfalls reference.
