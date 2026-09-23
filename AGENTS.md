# AGENTS.md — developing game-analytics-kit

This repository is a kit that gets **installed into game projects**. Work here changes what
every project receives on its next `install.py` run, so keep the contract in
[docs/DESIGN.md](docs/DESIGN.md) true: change the design first, then the code, then the skills.

## Rules

- `kit/` is Python **standard library only** (3.11+: `tomllib`). No requests, pandas, jinja.
  Skills may *suggest* pandas for ad-hoc research when it is installed; the engine never needs it.
- Nothing game-specific in `kit/`, `skills/`, `templates/`. Examples from real projects go into
  `docs/KNOWLEDGE.md` marked *(example)*.
- Skills: folder name = `name`; front matter has only `name` and `description`; body in English;
  no Claude-only syntax (`${CLAUDE_SKILL_DIR}`, `$ARGUMENTS`, `!` injection, `allowed-tools`),
  because the same folders are installed for Codex (`.agents/skills`). Commands in skills are
  always `py analytics/ga.py ...` run from the project root.
- Reports are the product: every change to `kit/gak/report/` must keep the sample in
  `docs/examples/sample-report/` building (`py docs/examples/sample-report/make_sample.py`).
- Secrets never appear in code, logs, reports, the database or git. Token lookup order is fixed
  in DESIGN §2.
- Windows is first class: junctions instead of symlinks, `py` launcher, backslash paths.

## Checks before committing

```bash
py kit/selftest.py
py tests/test_install.py
py docs/examples/sample-report/make_sample.py
py install.py <some scratch project folder> --dry-run
```

## Versioning

`VERSION` is semver. Bump it with every change a project would notice and add a line to
`CHANGELOG.md`. Projects record the installed version in `analytics/kit.install.json`.

Commit messages: `[Kit]`, `[Skills]`, `[Report]`, `[Install]`, `[Docs]` (several if needed) + ` - ` + short
description, e.g. `[Kit][Report] - 0.3.0: keymetrics and dropoff tables`.
