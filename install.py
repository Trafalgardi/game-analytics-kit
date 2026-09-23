#!/usr/bin/env python3
"""Install game-analytics-kit into a game project, update it, or remove it.

    py install.py <project>                 install (or update) into the project
    py install.py <project> --dry-run       show what would change
    py install.py <project> --link          link instead of copy (for developing the kit)
    py install.py <project> --uninstall     remove the kit and its skills, keep data

What goes where (see docs/DESIGN.md, section 2):
    skills/<name>/   -> <project>/.claude/skills/<name>/   (Claude Code)
                     -> <project>/.agents/skills/<name>/   (OpenAI Codex)
    kit/             -> <project>/analytics/kit/            (engine, replaced on every update)
    templates/*      -> <project>/analytics/...             (only files that do not exist yet,
                                                             except the launcher ga.py)

The kit owns only what it installed: every copied skill folder carries a `.gak-managed`
marker, and nothing without that marker is ever overwritten or removed. Project files -
analytics.toml, .env, data/, model/, queries/, notes/, imports/, reports/ - are never
touched by an update or an uninstall.

Standard library only; Python 3.9+.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

KIT_ROOT = Path(__file__).resolve().parent
MARKER = ".gak-managed"
AGENT_SKILL_DIRS = {"claude": Path(".claude") / "skills", "codex": Path(".agents") / "skills"}

# Template file -> path inside analytics/. The launcher is kit-owned and always refreshed;
# everything else is created once and then belongs to the project.
TEMPLATES = {
    "ga.py": ("ga.py", True),
    "analytics.toml": ("analytics.toml", False),
    "env.example": ("env.example", True),
    "gitignore": (".gitignore", False),
    "notes/project.md": ("notes/project.md", False),
    "notes/findings.md": ("notes/findings.md", False),
    "model/README.md": ("model/README.md", False),
    "queries/README.md": ("queries/README.md", False),
}
EMPTY_DIRS = ("data", "imports", "reports", "model", "queries", "notes")
IGNORED_IN_COPY = shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache")


class Plan:
    """Collects every file-system action first, so --dry-run prints exactly what install does."""

    def __init__(self, dry_run: bool):
        self.dry_run = dry_run
        self.lines: list[str] = []

    def note(self, line: str) -> None:
        self.lines.append(line)
        print(line)

    def remove_tree(self, path: Path) -> None:
        self.note(f"  remove  {path}")
        if not self.dry_run:
            if path.is_symlink() or _is_junction(path):
                path.unlink() if path.is_symlink() else os.rmdir(path)
            else:
                shutil.rmtree(path)

    def copy_tree(self, src: Path, dst: Path) -> None:
        self.note(f"  copy    {src.relative_to(KIT_ROOT)} -> {dst}")
        if not self.dry_run:
            shutil.copytree(src, dst, ignore=IGNORED_IN_COPY)

    def link_tree(self, src: Path, dst: Path) -> None:
        self.note(f"  link    {dst} -> {src}")
        if not self.dry_run:
            dst.parent.mkdir(parents=True, exist_ok=True)
            _make_dir_link(src, dst)

    def copy_file(self, src: Path, dst: Path) -> None:
        self.note(f"  write   {dst}")
        if not self.dry_run:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

    def write_text(self, dst: Path, text: str) -> None:
        self.note(f"  write   {dst}")
        if not self.dry_run:
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(text, encoding="utf-8")

    def mkdir(self, path: Path) -> None:
        if path.exists():
            return
        self.note(f"  mkdir   {path}")
        if not self.dry_run:
            path.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------------- #
# links (Windows junctions need no admin rights, symlinks do)
# --------------------------------------------------------------------------- #

def _is_junction(path: Path) -> bool:
    is_junction = getattr(os.path, "isjunction", None)
    return bool(is_junction and is_junction(path))


def _make_dir_link(src: Path, dst: Path) -> None:
    if os.name == "nt":
        import _winapi  # CPython on Windows; creates a junction without elevation

        _winapi.CreateJunction(str(src), str(dst))
    else:
        dst.symlink_to(src, target_is_directory=True)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def kit_version() -> str:
    return (KIT_ROOT / "VERSION").read_text(encoding="utf-8").strip()


def kit_commit() -> str | None:
    try:
        out = subprocess.run(["git", "-C", str(KIT_ROOT), "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=10)
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def kit_skills() -> list[Path]:
    return sorted(p for p in (KIT_ROOT / "skills").iterdir() if (p / "SKILL.md").is_file())


def check_target(project: Path, analytics_dir: Path) -> None:
    if not project.is_dir():
        sys.exit(f"error: project folder does not exist: {project}")
    if project.resolve() == KIT_ROOT:
        sys.exit("error: that is the kit repository itself; pass the game project folder")
    # Unity imports everything under Assets/ - an engine full of .py files there would be
    # imported as TextAssets and produce .meta churn.
    try:
        inside = analytics_dir.resolve().relative_to(project.resolve()).parts
    except ValueError:
        sys.exit(f"error: {analytics_dir} is outside the project {project}")
    if any(part.lower() == "assets" for part in inside):
        sys.exit(f"error: {analytics_dir} is inside an Assets folder; choose --analytics-dir outside it")
    if not (project / ".git").exists():
        print(f"warning: {project} is not a git root; skills are discovered from the folder the agent "
              "starts in and its parents, so install into the folder you open the agent in")


def owned(path: Path) -> bool:
    """A folder the kit may replace: installed by it earlier, or a link the kit made."""
    return (path / MARKER).exists() or path.is_symlink() or _is_junction(path)


# --------------------------------------------------------------------------- #
# install / update
# --------------------------------------------------------------------------- #

def install_skills(plan: Plan, project: Path, agents: list[str], link: bool) -> list[str]:
    installed = []
    version = kit_version()
    for agent in agents:
        root = project / AGENT_SKILL_DIRS[agent]
        for skill in kit_skills():
            dst = root / skill.name
            if dst.exists() or dst.is_symlink():
                if not owned(dst):
                    plan.note(f"  skip    {dst} exists and was not installed by the kit - rename it first")
                    continue
                plan.remove_tree(dst)
            if link:
                plan.link_tree(skill, dst)
            else:
                plan.copy_tree(skill, dst)
                plan.write_text(dst / MARKER, f"game-analytics-kit {version}\n")
            installed.append(f"{AGENT_SKILL_DIRS[agent].as_posix()}/{skill.name}")
    return installed


def install_kit(plan: Plan, analytics: Path, link: bool) -> None:
    dst = analytics / "kit"
    if dst.exists() or dst.is_symlink():
        plan.remove_tree(dst)
    if link:
        plan.link_tree(KIT_ROOT / "kit", dst)
        return
    plan.copy_tree(KIT_ROOT / "kit", dst)
    plan.copy_file(KIT_ROOT / "VERSION", dst / "VERSION")


def install_templates(plan: Plan, analytics: Path) -> None:
    for name in EMPTY_DIRS:
        plan.mkdir(analytics / name)
    for src_name, (dst_name, kit_owned) in TEMPLATES.items():
        src = KIT_ROOT / "templates" / src_name
        dst = analytics / dst_name
        if not src.exists():
            plan.note(f"  missing template {src_name} (kit bug) - skipped")
            continue
        if dst.exists() and not kit_owned:
            continue
        plan.copy_file(src, dst)


def write_install_record(plan: Plan, analytics: Path, agents: list[str], link: bool,
                         skills: list[str]) -> None:
    record = {
        "kit_version": kit_version(),
        "kit_commit": kit_commit(),
        "kit_path": str(KIT_ROOT),
        "installed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": "link" if link else "copy",
        "agents": agents,
        "skills": skills,
    }
    target = analytics / "kit.install.json"
    plan.write_text(target, json.dumps(record, indent=2, ensure_ascii=False) + "\n")


def cmd_install(args: argparse.Namespace) -> int:
    project = Path(args.project).resolve()
    analytics = (project / args.analytics_dir).resolve()
    check_target(project, analytics)
    agents = [a.strip() for a in args.agents.split(",") if a.strip()]
    unknown = [a for a in agents if a not in AGENT_SKILL_DIRS]
    if unknown:
        sys.exit(f"error: unknown agent(s) {unknown}; use {sorted(AGENT_SKILL_DIRS)}")

    previous = analytics / "kit.install.json"
    action = "update" if previous.exists() else "install"
    plan = Plan(args.dry_run)
    plan.note(f"{action} game-analytics-kit {kit_version()} into {project}"
              + ("  (dry run)" if args.dry_run else ""))

    skills = install_skills(plan, project, agents, args.link)
    install_kit(plan, analytics, args.link)
    install_templates(plan, analytics)
    write_install_record(plan, analytics, agents, args.link, skills)

    rel = analytics.relative_to(project).as_posix()
    print()
    print("done." if not args.dry_run else "dry run - nothing changed.")
    if action == "install":
        print(f"""
next steps:
  1. put the AppMetrica token into {rel}/.env (APPMETRICA_TOKEN=...) or, once for all
     projects, into ~/.config/game-analytics-kit/.env - never commit it
  2. check:            py {rel}/ga.py status
  3. ask your agent:   "подключи AppMetrica" (skill analytics-connect-appmetrica),
                       then "собери модель данных", "сделай аудит аналитики",
                       and any research question you have
""")
    return 0


# --------------------------------------------------------------------------- #
# uninstall
# --------------------------------------------------------------------------- #

def cmd_uninstall(args: argparse.Namespace) -> int:
    project = Path(args.project).resolve()
    analytics = (project / args.analytics_dir).resolve()
    plan = Plan(args.dry_run)
    plan.note(f"uninstall game-analytics-kit from {project}" + ("  (dry run)" if args.dry_run else ""))
    for rel in AGENT_SKILL_DIRS.values():
        root = project / rel
        for skill in kit_skills():
            dst = root / skill.name
            if (dst.exists() or dst.is_symlink()) and owned(dst):
                plan.remove_tree(dst)
    for kit_owned in (analytics / "kit", analytics / "ga.py", analytics / "env.example",
                      analytics / "kit.install.json"):
        if kit_owned.is_dir() or kit_owned.is_symlink() or _is_junction(kit_owned):
            plan.remove_tree(kit_owned)
        elif kit_owned.exists():
            plan.note(f"  remove  {kit_owned}")
            if not args.dry_run:
                kit_owned.unlink()
    print("\nkept: analytics.toml, .env, data/, model/, queries/, notes/, imports/, reports/")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("project", help="game project root (usually its git root)")
    parser.add_argument("--analytics-dir", default="analytics",
                        help="folder for the engine and project analytics files, relative to the project "
                             "(default: analytics)")
    parser.add_argument("--agents", default="claude,codex",
                        help="which agents get the skills: claude, codex or both (default)")
    parser.add_argument("--link", action="store_true",
                        help="link skills and kit to this repository instead of copying (kit development)")
    parser.add_argument("--dry-run", action="store_true", help="print the plan, change nothing")
    parser.add_argument("--uninstall", action="store_true",
                        help="remove the kit, the launcher and the kit's skills; keep project data")
    parser.add_argument("--update", action="store_true",
                        help="same as a plain install on an existing project (kept for readability)")
    return parser


def main(argv: list[str] | None = None) -> int:
    # Windows consoles and pipes default to cp1252; the next-steps text has Cyrillic in it.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    return cmd_uninstall(args) if args.uninstall else cmd_install(args)


if __name__ == "__main__":
    sys.exit(main())
