---
name: analytics-project-audit
description: "Audits how the game measures itself: finds analytics, ads and IAP SDKs, the analytics wrapper, event and parameter constants and every call site in the code, compares them with the events that actually arrive in the database, scores coverage against a checklist (install, FTUE, sessions, core loop, economy, ads, IAP, performance, errors, identity, attribution, A/B), detects telemetry traps, lists external data to request, and proposes a tracking plan. Produces the versioned 'tracking-audit' report and notes updates. Use when starting analytics in a project, after SDK or tracking changes, or on 'audit our analytics', 'what do we track', «аудит аналитики», «что мы трекаем», «каких событий не хватает», «почему события нет в данных». Not for building SQL views (analytics-data-model), answering product questions (analytics-research), or console exports (analytics-import-external)."
---

# Tracking audit

Commands run from the project root (conventions: the `analytics-kit` skill). Read
`analytics/notes/project.md` and `analytics/notes/findings.md` first. The audit proposes;
it does not change game code unless the owner asks (then follow the project's own agent
rules, e.g. its `CLAUDE.md` / `AGENTS.md`).

References — read when you reach the step:
- [references/sdk-search-patterns.md](references/sdk-search-patterns.md) — search patterns
  per engine and SDK (step 2–4).
- [references/coverage-checklist.md](references/coverage-checklist.md) — the checklist,
  telemetry traps and how to detect them in data (step 6–7).
- [references/tracking-plan-guide.md](references/tracking-plan-guide.md) — naming rules,
  plan table, tracking-spec outline (step 9).

## Inputs

- The game's source code.
- The database with at least `events` and `installations` (`status`). With no data yet,
  do a code-only audit and mark every data column "not checked".

## Procedure

1. **Open a report version**: `py analytics/ga.py report new tracking-audit --kind question --title "<the request>"`
   (the title is the request: «<Game> <version>: аудит аналитики, <date>»)
   (or `--from vK` when a previous audit exists). Keep scratch files in its `work/`.

2. **SDK inventory.** From package manifests and code: every analytics, attribution, ads,
   mediation, IAP and crash SDK with version, where it is initialized, and what it sends
   on its own (automatic events, revenue, sessions). Note consent/opt-out gates and
   compile flags that disable analytics in some builds.

3. **Find the analytics layer**: the wrapper/facade that sends events, which providers it
   fans out to, event-name and parameter-name constants, value mappings, parameters added
   to every event, per-provider limits it enforces.

4. **Enumerate events from code** into `work/code_events.csv`: event, parameters (with
   type and unit), call site (`file:line`, method), trigger, frequency (once per install
   / session / occurrence / periodic), guards (platform, build, flag), first commit
   (`git log -S "<name>" --oneline | tail -1`). Watch for dynamic names (string
   concatenation) and names stored in assets rather than code.

5. **Compare with data.** `py analytics/ga.py catalog --format json` (and again with
   `--since` = release day of the current public build). Per event:
   - in code and in data → check parameters: missing keys, type drift, constant values,
     implausible volumes (fires far more than the player acts);
   - in code, never in data → unreleased (added after the last public build), gated off,
     broken call path, or a name mismatch (case, prefix, truncation);
   - in data, not in code → older builds, SDK automatic events, another platform, or a
     dynamic name;
   - the first and last version in which each event appears:
     `sql "SELECT event_name, MIN(app_version_name), MAX(app_version_name), COUNT(DISTINCT appmetrica_device_id) FROM events GROUP BY 1"`
     (version strings sort as text — check by eye).

6. **Score coverage** against the checklist: each item covered / partial / missing /
   broken, with evidence (`file:line`, event counts, devices). A covered item that no one
   could turn into a number in five minutes is "partial".

7. **Telemetry traps.** Check every trap in the checklist reference against the data, for
   example: "failures" that coincide with an impression in the same second, timers that
   run through an ad pause, a latency field that actually measures view duration, fields
   that are always constant, suspicious CTR. Quantify each (rows, devices, share).

8. **External data needed.** Which questions the event stream cannot answer (spend,
   installs per network, store conversion, vitals, AdMob fill) and the exact export for
   each — console paths are in the `analytics-import-external` skill. This becomes the
   "Data I need from you" checklist.

9. **Tracking plan.** A prioritized table of proposed changes:

   | Priority | Event | Parameters | Where to fire (`file:method`) | Why (question it answers) |
   | --- | --- | --- | --- | --- |

   Fixes to broken or misleading events come before new events. If the owner wants the
   plan implemented, also write a tracking spec (outline in the plan guide), saved where
   the project keeps specs, or `analytics/notes/tracking-plan.md` if it has no place.

10. **Report** through the `analytics-report` skill, slug `tracking-audit`, in the report
    language, in the fixed skeleton (a question report):
    - 1 summary: tiles (coverage score, the worst defect with its count) and short answers —
      what we can answer today, what we cannot, the three most harmful gaps;
    - 2 product / 3 revenue (optional): the coverage table (item — status — evidence) for the
      product and the money areas;
    - 4 technical: SDK inventory, code vs data discrepancies, telemetry traps with counts,
      each with the metric it biases and the direction;
    - 6 hypotheses: what each defect does to the decisions ("H1: duplicated income events
      double the economy numbers"), how to confirm it after the fix;
    - 7 recommendations: the tracking plan, each item → its hypothesis, with the effect and
      how to verify the fix in data; then data requests with console paths; method.

11. **Notes.** Update `analytics/notes/project.md`: SDKs and versions, SDK key location,
    wrapper location, event dictionary changes, broken and dead fields, dev-build
    behaviour, whether `profile_id` is set. Add a dated entry to
    `analytics/notes/findings.md` with the report link.

## Rules

- Evidence for every claim: a `file:line` for code, a count with n for data.
- "Never arrived" needs a version check before it is called broken: compare with the
  first build that contains the call and with which builds players actually run.
- Do not trust an event's name — read what triggers it. A `*_failed` event can fire on
  success; a `*_sec` can measure the wrong interval.
- Performance matters in games: flag any event sent per frame or per physics tick, and
  propose aggregation (per match stats, periodic ticks) instead.
