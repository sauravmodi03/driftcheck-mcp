"""MCP server exposing driftcheck. Read-only: it never modifies files or services."""
from __future__ import annotations

from pathlib import Path

from mcp.server.mcpserver import MCPServer

from .core import DRIFT, collect, extract, verify

mcp = MCPServer("driftcheck")


@mcp.tool()
def check_docs(paths: list[str], include_ok: bool = False, scope: str | None = None) -> dict:
    """Check factual claims (file paths, local ports, systemd units, Forgejo repos) in markdown
    docs or directories of docs against the live system. Returns drifted claims with file:line and why.
    Set include_ok=true to also list claims that verified fine. Claims tagged
    `<!-- driftcheck: scope=X -->` are only checked when scope=X is passed."""
    results, errors = [], []
    for p in collect(paths):
        try:
            text = Path(p).expanduser().read_text(encoding="utf-8")
        except OSError as e:
            errors.append(f"{p}: {e.strerror or e}")
            continue
        results += verify(extract(text, p), scope)
    shown = results if include_ok else [r for r in results if r.status == DRIFT]
    return {
        "summary": {s: sum(r.status == s for r in results) for s in ("ok", "drift", "unverifiable", "skipped")},
        "claims": [r.to_dict() for r in shown],
        "errors": errors,
    }


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
