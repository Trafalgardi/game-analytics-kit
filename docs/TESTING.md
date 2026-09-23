# Testing the kit

Three layers, cheapest first.

## 1. Offline (every change)

```bash
py kit/selftest.py                                  # engine: sync path with a fake source, model, queries, csv import
py tests/test_install.py                            # installer: install, update, clashes, uninstall
py docs/examples/sample-report/make_sample.py       # report builder: every component and chart, two versions
```

## 2. Skill discovery (after changing skills)

Install into a real project, then ask each agent what it sees. Neither run may execute commands.

```bash
py install.py <project>
codex exec -C <project> --sandbox read-only "List the skills available to you whose names start with analytics-: name and first sentence of the description. Do not run commands."
cd <project> && claude -p "List the skills available to you whose names start with analytics-: name and first sentence of the description. Do not run commands."
```

Both must list all seven skills.

## 3. End to end on a real project (before a release)

A fresh agent that has never seen the kit must get from zero to a published report using only
the skills. Run it headless and keep the transcript:

1. **Claude Code:** `claude -p --dangerously-skip-permissions "Подключи AppMetrica и собери модель данных. Выгрузи последние 30 дней."`
   Expect: SDK key found in code, app resolved, sync done, `model/0*.sql` written and applied,
   `notes/project.md` filled.
2. **Codex:** `codex exec -C <project> --dangerously-bypass-approvals-and-sandbox "Сделай аудит аналитики проекта и выпусти отчёт."`
   Expect: `reports/tracking-audit/v001/report.html` built, a data-request checklist, notes updated.
3. **Either agent:** a real research question → `reports/<slug>/v001/report.html`, findings logged.
4. **Full review:** `claude -p --dangerously-skip-permissions "Сделай полный анализ игры за последние две недели"`.
   Expect: a `--kind full` report whose title is «<Game> <version>, <period>: <request>», all
   seven blocks, the four standard tables embedded with one population (`keymetrics` by
   version, `dropoff` with step times, `ordinals`, `leaving` next to a neutral event), numbered
   hypotheses with links, recommendations linked to them; the build passes the skeleton check.
   Compare its conclusions with what a human analyst found for the same game, if available.

Capture transcripts (`claude -p --output-format stream-json --verbose ... > run.jsonl`,
`codex exec --json ... > run.jsonl`) and summarise them:

```bash
py tests/transcript_summary.py run.jsonl
```

Read every transcript for places where the agent guessed, asked something the skill should
have answered, or ran a command that does not exist — each one is a skill bug.

If `codex exec` fails with "model requires a newer version of Codex", the configured default
model is newer than the CLI: pass a model the CLI knows (`-m gpt-5.6-sol`) or update Codex.
