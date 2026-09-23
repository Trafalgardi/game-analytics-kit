#!/usr/bin/env python3
"""Offline check of install.py against a throwaway project folder.

    py tests/test_install.py

Covers: fresh install (skills for both agents, kit, templates, record), update keeps project
files, a foreign skill with the same name is never overwritten, uninstall removes only what the
kit owns, an analytics dir inside Assets/ is refused.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
INSTALL = KIT / "install.py"
FAILURES: list[str] = []


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(INSTALL), *args], capture_output=True, text=True, encoding="utf-8", errors="replace")


def check(condition: bool, message: str) -> None:
    print(("ok   " if condition else "FAIL ") + message)
    if not condition:
        FAILURES.append(message)


def main() -> int:
    skills = sorted(p.name for p in (KIT / "skills").iterdir() if (p / "SKILL.md").is_file())
    check(len(skills) >= 1, f"kit has skills: {skills}")
    root = Path(tempfile.mkdtemp(prefix="gak-install-"))
    try:
        project = root / "game"
        (project / ".git").mkdir(parents=True)
        foreign = project / ".claude" / "skills" / "my-own-skill"
        foreign.mkdir(parents=True)
        (foreign / "SKILL.md").write_text("---\nname: my-own-skill\ndescription: x\n---\n", encoding="utf-8")

        result = run(str(project))
        check(result.returncode == 0, f"install exits 0 ({result.stderr.strip()[:200]})")
        analytics = project / "analytics"
        for agent_dir in (".claude/skills", ".agents/skills"):
            for name in skills:
                skill = project / agent_dir / name
                check((skill / "SKILL.md").is_file() and (skill / ".gak-managed").is_file(),
                      f"{agent_dir}/{name} installed with marker")
        check((foreign / "SKILL.md").is_file(), "foreign skill untouched")
        check((analytics / "kit" / "gak" / "cli.py").is_file(), "engine copied")
        check((analytics / "kit" / "VERSION").is_file(), "kit VERSION written")
        check((analytics / "ga.py").is_file(), "launcher written")
        for name in ("analytics.toml", ".gitignore", "notes/project.md", "notes/findings.md"):
            check((analytics / name).is_file(), f"template {name} created")
        record = json.loads((analytics / "kit.install.json").read_text(encoding="utf-8"))
        check(record["mode"] == "copy" and record["agents"] == ["claude", "codex"], "install record")

        status = subprocess.run([sys.executable, str(analytics / "ga.py"), "status"],
                                capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=project)
        check(status.returncode == 0, f"ga.py status runs ({status.stderr.strip()[:200]})")

        (analytics / "analytics.toml").write_text("# edited by the project\n", encoding="utf-8")
        (analytics / "notes" / "project.md").write_text("project facts\n", encoding="utf-8")
        (analytics / "data" / "analytics.db").write_bytes(b"db")
        result = run(str(project), "--update")
        check(result.returncode == 0, "update exits 0")
        check((analytics / "analytics.toml").read_text(encoding="utf-8") == "# edited by the project\n",
              "update keeps analytics.toml")
        check((analytics / "notes" / "project.md").read_text(encoding="utf-8") == "project facts\n",
              "update keeps notes")

        clash = project / ".agents" / "skills" / skills[0]
        shutil.rmtree(clash)
        clash.mkdir()
        (clash / "SKILL.md").write_text("mine", encoding="utf-8")
        result = run(str(project))
        check((clash / "SKILL.md").read_text(encoding="utf-8") == "mine", "unmarked same-name skill kept")
        check("skip" in result.stdout, "clash reported as skip")

        dry = run(str(project), "--uninstall", "--dry-run")
        check(dry.returncode == 0 and (analytics / "kit").exists(), "uninstall dry run changes nothing")
        result = run(str(project), "--uninstall")
        check(result.returncode == 0, "uninstall exits 0")
        check(not (analytics / "kit").exists() and not (analytics / "ga.py").exists(), "kit and launcher removed")
        check(not (project / ".claude" / "skills" / skills[0]).exists(), "managed skill removed")
        check((clash / "SKILL.md").exists(), "unmanaged skill kept on uninstall")
        check((analytics / "data" / "analytics.db").exists() and (analytics / "analytics.toml").exists(),
              "data and config kept on uninstall")

        unity = root / "unity"
        (unity / "Assets").mkdir(parents=True)
        result = run(str(unity), "--analytics-dir", "Assets/analytics")
        check(result.returncode != 0 and "Assets" in (result.stderr + result.stdout), "Assets/ refused")
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print(f"\n{'all passed' if not FAILURES else str(len(FAILURES)) + ' failed'}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
