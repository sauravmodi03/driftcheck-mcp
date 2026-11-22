# Changelog

## 0.1.0

- Extract and verify claims in markdown: file paths, local ports, systemd units, Forgejo repos.
- `<!-- driftcheck: scope=X | ignore -->` markers for claims that hold on another machine.
- Directory scanning, `--json`, exit code 1 on drift.
- `driftcheck timer`: customisable systemd timer generator.
- Optional read-only MCP server with a `check_docs` tool.
