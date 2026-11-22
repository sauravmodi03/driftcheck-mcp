"""Extract checkable claims from markdown and verify them. Stdlib only."""
from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
from dataclasses import dataclass, asdict
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

OK, DRIFT, UNKNOWN, SKIPPED = "ok", "drift", "unverifiable", "skipped"

_CODE = re.compile(r"`([^`\n]+)`")
_URL = re.compile(r"https?://[^\s`)\]>,]+")
_UNIT = re.compile(r"\b[\w@.-]+\.(?:service|timer)\b")
_PATH = re.compile(r"^(?:~|/)[\w@./+-]*$")
_MARKER = re.compile(r"<!--\s*driftcheck:\s*(ignore|scope=([\w.-]+))\s*-->")
_REMOTE = re.compile(r"\bforge:([\w.-]+)/([\w.-]+?)(?:\.git)?(?=[\s`)\],;]|$)")
_RESERVED = {"api", "user", "explore", "org", "admin", "repo", "assets", "login", "issues", "pulls"}
_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
_HOSTPORT = re.compile(r"(?<![\w./:-])(127\.0\.0\.1|localhost):(\d{2,5})\b(?!/)")


@dataclass(frozen=True)
class Claim:
    kind: str       # path | port | unit | command
    value: str
    file: str
    line: int
    scope: str | None = None  # only verified when this scope is active


@dataclass(frozen=True)
class Result:
    claim: Claim
    status: str
    detail: str

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


def _scoped(add, scope):
    return lambda kind, value, line: add(kind, value, line, scope)


def extract(text: str, file: str = "<text>") -> list[Claim]:
    """Pull checkable claims out of markdown. Deduplicated per (kind, value)."""
    seen: set[tuple[str, str]] = set()
    out: list[Claim] = []

    def add(kind: str, value: str, line: int, scope: str | None = None) -> None:
        if (kind, value) not in seen:
            seen.add((kind, value))
            out.append(Claim(kind, value, file, line, scope))

    in_fence = False
    pending = None  # marker from a standalone marker line, applies to next line
    for n, line in enumerate(text.splitlines(), 1):
        m = _MARKER.search(line)
        if m and not _MARKER.sub("", line).strip():
            pending = m
            continue
        marker, pending = (m or pending), None
        if marker and marker.group(1) == "ignore":
            continue
        scope = marker.group(2) if marker else None
        emit = _scoped(add, scope)
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        for u in _URL.findall(line):
            p = urlparse(u.rstrip(".:;"))
            if p.hostname in _LOCAL_HOSTS and p.port:
                emit("port", f"{p.hostname}:{p.port}", n)
                seg = [x for x in p.path.split("/") if x]
                if p.port == _forgejo_port() and len(seg) >= 2 and seg[0] not in _RESERVED:
                    emit("repo", f"{seg[0]}/{seg[1].removesuffix('.git')}", n)
        for owner, name in _REMOTE.findall(line):
            emit("repo", f"{owner}/{name}", n)
        for host, port in _HOSTPORT.findall(line):
            emit("port", f"{host}:{port}", n)
        for m in _UNIT.findall(line):
            emit("unit", m, n)
        for code in _CODE.findall(line):
            tok = code.split()[0] if code.split() else ""
            if not _PATH.match(tok) or tok in ("/", "~", "~/"):
                continue
            if "*" in tok or "<" in tok:
                continue
            emit("path", tok.rstrip(".,;:"), n)
    return out


def _check_path(v: str) -> tuple[str, str]:
    p = os.path.expanduser(v)
    if os.path.lexists(p):
        return OK, "exists"
    top = p.split("/")[1] if p.startswith("/") else None
    if top and not os.path.lexists("/" + top):
        return UNKNOWN, f"/{top} does not exist here; may be a URL route, not a file"
    return DRIFT, f"{p} does not exist"


def _check_port(v: str) -> tuple[str, str]:
    host, _, port = v.rpartition(":")
    try:
        with socket.create_connection((host, int(port)), timeout=1.5):
            return OK, "accepting connections"
    except OSError as e:
        return DRIFT, f"nothing listening ({e.strerror or e})"


def _check_unit(v: str) -> tuple[str, str]:
    if not shutil.which("systemctl"):
        return UNKNOWN, "systemctl not available"
    for scope in (["--user"], []):
        r = subprocess.run(["systemctl", *scope, "cat", v],
                           capture_output=True, text=True, timeout=10)
        if r.returncode != 0:
            continue
        state = subprocess.run(["systemctl", *scope, "is-active", v],
                               capture_output=True, text=True, timeout=10).stdout.strip()
        where = "user" if scope else "system"
        if state == "failed":
            return DRIFT, f"unit exists ({where}) but is failed"
        if v.endswith(".timer") and state != "active":
            return DRIFT, f"timer exists ({where}) but is {state or 'unknown'}"
        return OK, f"unit file found ({where}), {state or 'unknown'}"
    return DRIFT, "no such systemd unit (user or system)"


def _forgejo_url() -> str:
    return os.environ.get("FORGEJO_URL", "http://127.0.0.1:3000").rstrip("/")


def _forgejo_port() -> int | None:
    return urlparse(_forgejo_url()).port


def _forgejo_token() -> str | None:
    """Token from $FORGEJO_TOKEN or ~/.config/forgejo-token.env. Never logged."""
    if os.environ.get("FORGEJO_TOKEN"):
        return os.environ["FORGEJO_TOKEN"]
    try:
        for line in (Path.home() / ".config/forgejo-token.env").read_text().splitlines():
            k, _, v = line.partition("=")
            if k.strip() == "FORGEJO_TOKEN":
                return v.strip().strip("\"'")
    except OSError:
        pass
    return None


def _check_repo(v: str) -> tuple[str, str]:
    req = urllib.request.Request(f"{_forgejo_url()}/api/v1/repos/{v}")
    token = _forgejo_token()
    if token:
        req.add_header("Authorization", f"token {token}")
    detail = ""
    for attempt in range(2):  # one retry: transient errors must not read as drift
        try:
            with urllib.request.urlopen(req, timeout=5):
                return OK, "repo exists on Forgejo"
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return DRIFT, "repo not found on Forgejo" + ("" if token else " (no token; may be private)")
            detail = f"Forgejo API returned HTTP {e.code}"
            if e.code < 500:
                break
        except (urllib.error.URLError, OSError) as e:
            detail = f"Forgejo unreachable ({getattr(e, 'reason', e)})"
    return UNKNOWN, detail


def collect(paths: list[str]) -> list[str]:
    """Expand directories to the markdown files inside them."""
    out: list[str] = []
    for p in paths:
        q = Path(p).expanduser()
        out += sorted(map(str, q.rglob("*.md"))) if q.is_dir() else [str(q)]
    return out


_CHECKS = {"path": _check_path, "port": _check_port, "unit": _check_unit, "repo": _check_repo}


def verify(claims: list[Claim], scope: str | None = None) -> list[Result]:
    """Verify claims. Claims tagged with a scope are only checked when it matches
    `scope` (default: $DRIFTCHECK_SCOPE); otherwise they are reported as skipped."""
    scope = scope or os.environ.get("DRIFTCHECK_SCOPE")
    results = []
    for c in claims:
        if c.scope and c.scope != scope:
            results.append(Result(c, SKIPPED, f"scope '{c.scope}' not active"))
            continue
        fn = _CHECKS.get(c.kind)
        status, detail = fn(c.value) if fn else (UNKNOWN, "no checker")
        results.append(Result(c, status, detail))
    return results
