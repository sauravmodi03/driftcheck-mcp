"""Generate (and optionally install) a systemd user timer that runs driftcheck."""
from __future__ import annotations

import argparse
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")
_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _quote(arg: str) -> str:
    """Quote one ExecStart argument for systemd ('%' must be doubled)."""
    arg = arg.replace("%", "%%")
    return shlex.quote(arg) if re.search(r"[^\w@%+=:,./-]", arg) else arg


def _clean(value: str, what: str) -> str:
    if any(ord(c) < 32 for c in value):
        raise ValueError(f"{what} must not contain control characters")
    return value


def render(name: str, calendar: str, exec_cmd: list[str], paths: list[str],
           scope: str | None, persistent: bool = True) -> tuple[str, str]:
    """Return (service_unit, timer_unit) text."""
    if not _NAME.match(name):
        raise ValueError(f"invalid unit name: {name!r}")
    _clean(calendar, "calendar")
    args = [*exec_cmd, *( ["--scope", scope] if scope else [] ), *paths]
    for a in args:
        _clean(a, "argument")
    service = (
        "[Unit]\n"
        f"Description=driftcheck: verify docs against the live system ({name})\n"
        "[Service]\nType=oneshot\n"
        f"ExecStart={' '.join(_quote(a) for a in args)}\n"
    )
    timer = (
        "[Unit]\n"
        f"Description=driftcheck: scheduled doc-drift check ({name})\n"
        "[Timer]\n"
        f"OnCalendar={calendar}\n"
        f"Persistent={'true' if persistent else 'false'}\n"
        "[Install]\nWantedBy=timers.target\n"
    )
    return service, timer


def _default_exec() -> list[str]:
    exe = shutil.which("driftcheck")
    if not exe:
        raise SystemExit("driftcheck is not on PATH; install it (`uv tool install driftcheck-mcp`) "
                         "or pass --exec '<command that runs driftcheck>'")
    return [os.path.realpath(exe)]


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="driftcheck timer",
        description="Generate a systemd user timer that runs driftcheck. Prints by default; "
                    "--install writes the units and enables the timer; --remove undoes it.")
    ap.add_argument("paths", nargs="*", help="files or directories to check")
    when = ap.add_mutually_exclusive_group()
    when.add_argument("--at", default="04:10", metavar="HH:MM", help="daily at this time (default 04:10)")
    when.add_argument("--calendar", metavar="EXPR", help="any systemd OnCalendar expression, e.g. 'Mon..Fri 08:00' or 'hourly'")
    ap.add_argument("--scope", help="scope passed to driftcheck (see scope markers)")
    ap.add_argument("--name", default="driftcheck", help="unit name (default driftcheck); use several names for several schedules")
    ap.add_argument("--exec", dest="exec_cmd", help="command that runs driftcheck (default: the one on PATH)")
    ap.add_argument("--no-persistent", action="store_true", help="do not catch up on runs missed while the machine was off")
    ap.add_argument("--unit-dir", default="~/.config/systemd/user")
    act = ap.add_mutually_exclusive_group()
    act.add_argument("--install", action="store_true", help="write units, daemon-reload, enable --now")
    act.add_argument("--remove", action="store_true", help="disable and delete the units")
    ap.add_argument("--no-enable", action="store_true", help="with --install: write files only")
    a = ap.parse_args(argv)

    udir = Path(a.unit_dir).expanduser()
    svc_path, tmr_path = udir / f"{a.name}.service", udir / f"{a.name}.timer"

    def systemctl(*args: str) -> None:
        subprocess.run(["systemctl", "--user", *args], check=True)

    if a.remove:
        if not _NAME.match(a.name):
            raise SystemExit(f"invalid unit name: {a.name!r}")
        if not a.no_enable:
            subprocess.run(["systemctl", "--user", "disable", "--now", f"{a.name}.timer"], check=False)
        for p in (svc_path, tmr_path):
            p.unlink(missing_ok=True)
        if not a.no_enable:
            systemctl("daemon-reload")
        print(f"removed {a.name}.service / {a.name}.timer")
        return 0

    if not a.paths:
        ap.error("give at least one file or directory to check")
    if not a.calendar and not _HHMM.match(a.at):
        ap.error("--at must be HH:MM (24h)")
    calendar = a.calendar or f"*-*-* {a.at}"
    exec_cmd = shlex.split(a.exec_cmd) if a.exec_cmd else _default_exec()
    paths = [os.path.abspath(os.path.expanduser(p)) for p in a.paths]
    try:
        service, timer = render(a.name, calendar, exec_cmd, paths, a.scope, not a.no_persistent)
    except ValueError as e:
        ap.error(str(e))

    if not a.install:
        print(f"# {svc_path}\n{service}\n# {tmr_path}\n{timer}"
              f"# dry run: add --install to write these and enable the timer", file=sys.stdout)
        return 0
    udir.mkdir(parents=True, exist_ok=True)
    svc_path.write_text(service)
    tmr_path.write_text(timer)
    print(f"wrote {svc_path} and {tmr_path}")
    if not a.no_enable:
        systemctl("daemon-reload")
        systemctl("enable", "--now", f"{a.name}.timer")
        print(f"enabled {a.name}.timer")
    return 0
