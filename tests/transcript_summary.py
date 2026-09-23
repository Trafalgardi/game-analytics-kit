#!/usr/bin/env python3
"""Summarise a headless agent run for skill debugging.

    claude -p --output-format stream-json --verbose "..." > run.jsonl
    py tests/transcript_summary.py run.jsonl

Prints, in order: which skills the agent loaded, every shell command with its exit status,
files it wrote, and the final answer. Codex transcripts (`codex exec --json`) are read too.
Skill bugs show up as commands that do not exist, repeated failures, or guesses.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def short(text: str, limit: int = 160) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def claude_events(lines):
    pending = {}
    for raw in lines:
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue
        kind = event.get("type")
        if kind == "assistant":
            for block in event.get("message", {}).get("content", []):
                if block.get("type") == "tool_use":
                    name, args = block.get("name"), block.get("input", {})
                    pending[block.get("id")] = (name, args)
                    if name == "Skill":
                        yield f"SKILL  {args.get('skill')}"
                    elif name in ("Bash", "PowerShell"):
                        yield f"RUN    {short(args.get('command', ''))}"
                    elif name in ("Write", "Edit"):
                        yield f"WRITE  {args.get('file_path')}"
                    elif name == "Read" and "SKILL.md" in str(args.get("file_path", "")) or \
                            name == "Read" and "/references/" in str(args.get("file_path", "")).replace("\\", "/"):
                        yield f"READ   {args.get('file_path')}"
        elif kind == "user":
            for block in event.get("message", {}).get("content", []) or []:
                if isinstance(block, dict) and block.get("type") == "tool_result" and block.get("is_error"):
                    name, args = pending.get(block.get("tool_use_id"), ("?", {}))
                    content = block.get("content")
                    text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
                    yield f"  FAIL {name}: {short(text, 220)}"
        elif kind == "result":
            yield ""
            yield f"RESULT ({event.get('subtype')}, {event.get('num_turns')} turns, "
            yield f"        {round((event.get('duration_ms') or 0) / 60000, 1)} min, ${event.get('total_cost_usd')})"
            yield str(event.get("result", ""))


def codex_events(lines):
    for raw in lines:
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue
        item = event.get("item") or {}
        itype = item.get("type") or item.get("item_type")
        if event.get("type") == "item.completed" and itype == "command_execution":
            status = item.get("exit_code")
            yield f"RUN    [{status}] {short(item.get('command', ''))}"
        elif event.get("type") == "item.completed" and itype == "file_change":
            for change in item.get("changes", []):
                yield f"WRITE  {change.get('path')}"
        elif event.get("type") == "item.completed" and itype == "agent_message":
            yield f"SAY    {short(item.get('text', ''), 400)}"


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    path = Path(sys.argv[1])
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    is_codex = any('"thread.started"' in line or '"item.completed"' in line for line in lines[:50])
    for line in (codex_events if is_codex else claude_events)(lines):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
