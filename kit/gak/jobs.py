"""Detached sync jobs: a sync that outlives the agent that started it.

Agents run shell commands under time limits (Claude Code stops waiting after 10 minutes,
a headless `claude -p` or `codex exec` ends when the model stops talking, and anything the
agent started in its own background dies with it). A sync of a few weeks waits tens of
minutes for AppMetrica to prepare exports. So:

    ga.py sync --background ...   starts the same sync as a detached process that writes
                                  data/sync.log and data/sync.state.json, and returns at once;
    ga.py sync --wait             follows the log and returns when the job ends, or after
                                  --timeout seconds with exit code 3 ("still running, wait again");
    ga.py status                  shows the running or the last job.

Only one sync may write the database at a time; a foreground sync refuses to start while a
background job is alive.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from . import GakError

STATE_NAME = "sync.state.json"
LOG_NAME = "sync.log"
ENV_STATE = "GAK_JOB_STATE"
STILL_RUNNING = 3
POLL_SEC = 5

Log = Callable[[str], None]


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def paths(data_dir: Path) -> tuple[Path, Path]:
    return data_dir / STATE_NAME, data_dir / LOG_NAME


def read_state(data_dir: Path) -> dict | None:
    state_path, _ = paths(data_dir)
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write_state(state_path: Path, state: dict) -> None:
    tmp = state_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, state_path)


def pid_alive(pid: int) -> bool:
    """Whether a process exists. Never os.kill(pid, 0) on Windows: it terminates the process."""
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def running_job(data_dir: Path) -> dict | None:
    state = read_state(data_dir)
    if state and state.get("status") == "running" and pid_alive(int(state.get("pid", 0))):
        return state
    return None


def ensure_idle(data_dir: Path) -> None:
    job = running_job(data_dir)
    if job and str(job.get("pid")) != str(os.getpid()):
        raise GakError(f"a background sync is running (pid {job['pid']}, started {job['started_at']}); "
                       "follow it with `ga.py sync --wait`")


def start(launcher: Path, data_dir: Path, argv: list[str], log: Log) -> dict:
    """Start `ga.py <argv>` detached, with stdout and stderr going to data/sync.log."""
    ensure_idle(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    state_path, log_path = paths(data_dir)
    if log_path.exists():
        os.replace(log_path, log_path.with_suffix(".log.1"))
    env = dict(os.environ, **{ENV_STATE: str(state_path), "PYTHONUNBUFFERED": "1",
                              "PYTHONIOENCODING": "utf-8"})
    command = [sys.executable, str(launcher), *argv]
    with open(log_path, "ab") as sink:
        process = _spawn(command, sink, env, launcher.parent.parent)
    state = {"pid": process.pid, "status": "running", "started_at": _now(),
             "command": "ga.py " + " ".join(argv), "log": log_path.name}
    _write_state(state_path, state)
    log(f"background sync started (pid {process.pid}); log: {log_path}")
    log("follow it with `py analytics/ga.py sync --wait` (repeat while it says 'still running')")
    return state


def _spawn(command: list[str], sink, env: dict, cwd: Path) -> subprocess.Popen:
    kwargs = dict(stdin=subprocess.DEVNULL, stdout=sink, stderr=subprocess.STDOUT, env=env,
                  cwd=str(cwd), close_fds=True)
    if os.name != "nt":
        return subprocess.Popen(command, start_new_session=True, **kwargs)
    detached = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | \
        getattr(subprocess, "CREATE_NO_WINDOW", 0)
    breakaway = 0x01000000  # CREATE_BREAKAWAY_FROM_JOB: survive the agent's job object
    try:
        return subprocess.Popen(command, creationflags=detached | breakaway, **kwargs)
    except OSError:
        # The parent's job forbids breakaway; the job then lives as long as that job does.
        return subprocess.Popen(command, creationflags=detached, **kwargs)


def finish(exit_code: int) -> None:
    """Called by the detached child when its sync ends (success or failure)."""
    state_path = os.environ.get(ENV_STATE)
    if not state_path:
        return
    path = Path(state_path)
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {"pid": os.getpid()}
    state.update(status="done" if exit_code == 0 else "failed", exit_code=exit_code,
                 finished_at=_now())
    _write_state(path, state)


def wait(data_dir: Path, timeout: float, log: Log) -> int:
    """Stream new log lines until the job ends; exit code of the job, or STILL_RUNNING."""
    state = read_state(data_dir)
    if not state:
        log("no background sync has been started here")
        return 0
    _, log_path = paths(data_dir)
    offset = _recap(log_path, log)
    deadline = time.monotonic() + timeout
    while True:
        offset = _drain(log_path, offset, log)
        state = read_state(data_dir) or state
        if state.get("status") != "running":
            code = int(state.get("exit_code", 1))
            log(f"background sync {state['status']} at {state.get('finished_at')} (exit {code})")
            return code
        if not pid_alive(int(state.get("pid", 0))):
            _drain(log_path, offset, log)
            log(f"background sync (pid {state.get('pid')}) is gone without finishing; "
                f"read {log_path} and start it again")
            return 1
        if time.monotonic() >= deadline:
            log(f"still running after {timeout:.0f}s (pid {state['pid']}); run `ga.py sync --wait` again")
            return STILL_RUNNING
        time.sleep(POLL_SEC)


def _recap(log_path: Path, log: Log, keep: int = 6) -> int:
    """Show only the tail of what is already logged; an agent calling --wait in a loop must
    not re-read the whole log each time. Returns the offset to follow from."""
    try:
        data = log_path.read_bytes()
    except OSError:
        return 0
    lines = data.decode("utf-8", errors="replace").splitlines()
    if len(lines) > keep:
        log(f"... {len(lines) - keep} earlier line(s) in {log_path.name}")
    for line in lines[-keep:]:
        log(line)
    return len(data)


def _drain(log_path: Path, offset: int, log: Log) -> int:
    try:
        with open(log_path, "rb") as handle:
            handle.seek(offset)
            chunk = handle.read()
    except OSError:
        return offset
    if chunk:
        for line in chunk.decode("utf-8", errors="replace").splitlines():
            log(line)
    return offset + len(chunk)


def describe(data_dir: Path) -> str | None:
    """One status line about the running or the last job."""
    state = read_state(data_dir)
    if not state:
        return None
    if state.get("status") == "running":
        if pid_alive(int(state.get("pid", 0))):
            return (f"sync job: running since {state['started_at']} (pid {state['pid']}); "
                    f"`ga.py sync --wait` follows it")
        return f"sync job: started {state['started_at']} and died without finishing; see data/{LOG_NAME}"
    return f"last sync job: {state['status']} at {state.get('finished_at')} (exit {state.get('exit_code')})"
