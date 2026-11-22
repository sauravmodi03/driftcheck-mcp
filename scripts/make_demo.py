"""Record a real driftcheck session in a sandbox and render it as an animated GIF.

Runs every command for real (no faked output), then draws terminal frames with
ImageMagick. Usage: python3 scripts/make_demo.py docs/demo.gif [driftcheck command]
"""
from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time

COLS, ROWS, PT, LH, PAD = 100, 29, 15, 21, 18
BG, FG, DIM, PROMPT = "#0d1117", "#c9d1d9", "#8b949e", "#58a6ff"
RED, GREEN, YELLOW = "#ff7b72", "#3fb950", "#d29922"
FONT = "DejaVu-Sans-Mono"


def esc(text: str) -> str:
    """ImageMagick treats % in -annotate text as an escape."""
    return text.replace("%", "%%")


def color(line: str) -> str:
    """Colour for a line of command output."""
    if line.startswith("DRIFT"):
        return RED
    if line.startswith("OK"):
        return GREEN
    if line.startswith("# exit code"):
        return YELLOW
    return DIM


def main() -> None:
    out_gif = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "demo.gif")
    dc = sys.argv[2] if len(sys.argv) > 2 else "driftcheck"
    sandbox = "/tmp/dcdemo"
    if os.path.exists(sandbox):
        sys.exit(f"{sandbox} already exists; remove it first (this script will not delete it for you)")
    os.makedirs(sandbox)
    with open(f"{sandbox}/config.yaml", "w") as f:
        f.write("debug: false\n")
    with open(f"{sandbox}/CLAUDE.md", "w") as f:
        f.write("# Agent notes\n"
                "- Dev server runs on http://127.0.0.1:8765\n"
                "- App config lives in `/tmp/dcdemo/config.yaml`\n"
                "- Deploy script: `/tmp/dcdemo/deploy.sh`\n")
    open(f"{sandbox}/deploy.sh", "w").close()
    server = subprocess.Popen([sys.executable, "-m", "http.server", "8765", "--bind", "127.0.0.1"],
                              cwd=sandbox, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.8)

    def run(cmd: str) -> list[str]:
        r = subprocess.run(cmd, shell=True, cwd=sandbox, capture_output=True, text=True)
        out = (r.stdout + r.stderr).rstrip("\n").splitlines()
        return out + ([f"# exit code {r.returncode}"] if "driftcheck" in cmd else [])

    def stop_server() -> list[str]:
        server.terminate(); server.wait()
        return []

    script = [
        ("# Your agent trusts CLAUDE.md. Is it still true?", None),
        ("$ cat CLAUDE.md", lambda: run("cat CLAUDE.md")),
        (f"$ driftcheck CLAUDE.md --all", lambda: run(f"{dc} CLAUDE.md --all")),
        ("# A week later the dev server is shut down, and someone renames the config:", stop_server),
        ("$ mv config.yaml settings.yaml", lambda: run("mv config.yaml settings.yaml")),
        ("$ driftcheck CLAUDE.md", lambda: run(f"{dc} CLAUDE.md")),
        ("# Caught before the agent acted on stale facts.", None),
    ]

    screen: list[str] = []
    narration: set[int] = set()  # indexes of screen lines that are narration
    frames: list[tuple[list[tuple[str, bool]], int]] = []  # ((line, is_narration), delay 1/100 s)

    def snap(delay: int) -> None:
        start = max(0, len(screen) - ROWS)
        frames.append(([(l, i + start in narration) for i, l in enumerate(screen[start:])], delay))

    try:
        for text, action in script:
            if text.startswith("$ "):
                screen.append("$ ")
                cmd = text[2:]
                for i in range(0, len(cmd), 2):
                    screen[-1] = "$ " + cmd[: i + 2]
                    snap(4)
                snap(35)
                out = action() if action else []
                screen.extend(line[:COLS] for line in out)
                snap(260 if "driftcheck" in text else 90)
            else:
                if action:
                    action()
                narration.add(len(screen))
                screen.append(text)
                snap(160)
            screen.append("")
        snap(400)
    finally:
        if server.poll() is None:
            server.terminate()
        shutil.rmtree(sandbox, ignore_errors=True)

    width = PAD * 2 + int(COLS * PT * 0.61)
    height = PAD * 2 + ROWS * LH
    with tempfile.TemporaryDirectory() as tmp:
        args = []
        for n, (lines, delay) in enumerate(frames):
            png = f"{tmp}/f{n:04d}.png"
            cmd = ["convert", "-size", f"{width}x{height}", f"xc:{BG}", "-font", FONT, "-pointsize", str(PT)]
            for i, (line, is_narration) in enumerate(lines):
                if not line:
                    continue
                y = PAD + (i + 1) * LH - 5
                if is_narration:
                    cmd += ["-fill", YELLOW, "-annotate", f"+{PAD}+{y}", esc(line)]
                elif line.startswith("$ "):
                    cmd += ["-fill", PROMPT, "-annotate", f"+{PAD}+{y}", "$"]
                    cmd += ["-fill", FG, "-annotate", f"+{PAD + int(PT * 0.61 * 2)}+{y}", esc(line[2:])]
                else:
                    cmd += ["-fill", color(line), "-annotate", f"+{PAD}+{y}", esc(line)]
            subprocess.run(cmd + [png], check=True)
            args += ["-delay", str(delay), png]
        subprocess.run(["convert", *args, "-loop", "0", "-layers", "Optimize", out_gif], check=True)
    print(f"wrote {out_gif} ({len(frames)} frames, {os.path.getsize(out_gif)//1024} KiB)")


if __name__ == "__main__":
    main()
