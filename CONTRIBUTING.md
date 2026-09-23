# Contributing

The kit is installed into game projects: a change here reaches every project on its next
`install.py` run. Keep the contract in [docs/DESIGN.md](docs/DESIGN.md) true — change the
design first, then the code, then the skills. The rules for agents working on the kit are in
[AGENTS.md](AGENTS.md); this page is the short version for people.

## Tests

Run all four before every commit; they are offline and take seconds:

```bash
py kit/selftest.py                               # engine on synthetic data (no token, no network)
py tests/test_install.py                         # install, update, clashes, uninstall
py docs/examples/sample-report/make_sample.py    # report builder: every component, both kinds
py install.py <scratch project folder> --dry-run
```

A change to `kit/gak/report/` must keep the examples in `docs/examples/sample-report/`
building; commit the regenerated examples — the site publishes them. CI runs the same checks
on Linux, macOS and Windows for every push and pull request. A change to the skills is tested on a real project
with fresh agents, as [docs/TESTING.md](docs/TESTING.md) describes; add the run to
[docs/TEST_LOG.md](docs/TEST_LOG.md) with what broke and what changed because of it.

## Engine

- `kit/` is Python **standard library only** (3.11+, `tomllib`). No requests, pandas, jinja.
- Windows is first class: junctions instead of symlinks, the `py` launcher, backslash paths.
- Every command prints plain text an agent can read; a failure is one `error: ...` line on
  stderr and a non-zero exit code.
- New behaviour gets a check in `kit/selftest.py`.

## Skills

- Folder name = `name`; the front matter has only `name` and `description`; the body is English.
- No Claude-only syntax (`${CLAUDE_SKILL_DIR}`, `$ARGUMENTS`, `!` injection, `allowed-tools`):
  the same folders are installed for Codex.
- Commands in skills are always `py analytics/ga.py ...`, run from the project root.
- Keep `SKILL.md` short; details go into `references/*.md`.
- Nothing game-specific in `kit/`, `skills/` or `templates/`. Lessons from real projects go into
  [docs/KNOWLEDGE.md](docs/KNOWLEDGE.md), anonymised and marked *(example)*.

## Adding a data source

One module in `kit/gak/sources/` implementing the `Source` interface (docs/DESIGN.md §3) plus
its fields module, registered in `kit/gak/sources/__init__.py`; sync, storage, sampling and
the disk guard are generic. Add a fake of it to `kit/selftest.py` and a connect skill or a
section of one.

## Secrets and private data

Tokens never appear in code, logs, reports, the database or git. Do not commit game names,
application ids, SDK keys, real metrics tied to a game, e-mails or local paths; use
`<kit>`, `<project>` and made-up numbers in docs and examples.

## Versioning and commits

- `VERSION` is semver. Bump it with every change a project would notice and add a line to
  [CHANGELOG.md](CHANGELOG.md).
- Commit messages: `[Kit]`, `[Skills]`, `[Report]`, `[Install]`, `[Docs]` (several if needed),
  then ` - ` and a short description, e.g. `[Kit][Report] - 0.3.0: keymetrics and dropoff tables`.
