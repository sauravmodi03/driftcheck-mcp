# driftcheck

**Your agent's context files rot. driftcheck tells you which facts are no longer true.**

`CLAUDE.md`, runbooks and memory notes say things like "the app listens on
:3000", "restarts use `foo.service`", "the code lives in repo X". When those
go stale, an agent acts on them with full confidence. `driftcheck` extracts
the checkable claims from markdown and verifies each one against the live
system. It is deterministic: no LLM is involved in checking.

- Zero runtime dependencies (stdlib only); the MCP server is an optional extra.
- Read-only: it never changes files, services or repos.
- Exit code 1 on drift, so it drops into CI or a systemd timer.

## Install

    uvx driftcheck CLAUDE.md                       # run without installing
    uv tool install driftcheck                     # or install the CLI
    uv tool install "driftcheck[mcp]"              # CLI + MCP server

(From a checkout: `uv run driftcheck CLAUDE.md`.)

## Usage

    driftcheck CLAUDE.md                 # report drift only
    driftcheck CLAUDE.md --all           # also list ok / unverifiable / skipped
    driftcheck docs/ ~/notes/            # directories: every *.md inside
    driftcheck CLAUDE.md --json          # machine-readable
    driftcheck CLAUDE.md --scope mac     # also check claims tagged scope=mac

## What it checks

| Claim in the doc | How it is verified |
|---|---|
| `` `~/bin/tool` ``, `` `/etc/foo.conf` `` | the path exists |
| `http://127.0.0.1:3000`, `localhost:2222` | something accepts connections |
| `foo.service`, `bar.timer` | systemd unit exists and is healthy (failed units and inactive timers are drift) |
| `forge:owner/repo`, repo URLs on your Forgejo | the repo exists via the Forgejo API |

Each result is one of `ok`, `drift`, `unverifiable` (could not be checked
reliably, e.g. Forgejo unreachable) or `skipped` (out of scope).

## Claims that are true somewhere else

A doc often describes several machines. Tag claims that only hold elsewhere
so they do not raise false alarms:

    tunnel 127.0.0.1:12222 <!-- driftcheck: scope=mac -->   # checked only with --scope mac
    <!-- driftcheck: ignore -->                              # alone on a line: skips the next line

Scoped claims are `skipped` unless the scope is active (`--scope X` or
`$DRIFTCHECK_SCOPE`).

## Run it on a schedule

`driftcheck timer` generates a systemd user timer. The schedule, targets and
scope are all arguments. It prints the units by default (a dry run):

    driftcheck timer CLAUDE.md notes/                        # daily 04:10, print only
    driftcheck timer CLAUDE.md --at 07:30 --install          # daily at 07:30, write + enable
    driftcheck timer CLAUDE.md --calendar "Mon..Fri 08:00" --scope pod --install
    driftcheck timer docs/ --name docs-check --calendar hourly --install   # several schedules: use --name
    driftcheck timer --name docs-check --remove              # disable and delete

`--calendar` takes any systemd `OnCalendar` expression. Other options:
`--exec` (command that runs driftcheck, default the one on `PATH`),
`--no-persistent` (skip runs missed while the machine was off),
`--unit-dir`, and `--no-enable` (write files only). To change a schedule, run the
command again with new arguments. Drift makes the run fail, so it shows up in
`systemctl --user --failed` and `journalctl --user -u <name>.service`.

## Demo

`examples/stale-runbook.md` is a runbook that has rotted (reproducible on any Linux machine):

```
$ driftcheck examples/stale-runbook.md --all
DRIFT        examples/stale-runbook.md:3  path /tmp/driftcheck-demo/build.sh  - /tmp/driftcheck-demo/build.sh does not exist
DRIFT        examples/stale-runbook.md:4  port 127.0.0.1:9  - nothing listening (Connection refused)
DRIFT        examples/stale-runbook.md:5  unit old-worker.service  - no such systemd unit (user or system)
DRIFT        examples/stale-runbook.md:6  path /tmp/driftcheck-demo-config.yaml  - /tmp/driftcheck-demo-config.yaml does not exist
OK           examples/stale-runbook.md:7  path /etc/hostname  - exists

5 claims: 1 ok, 4 drift, 0 unverifiable, 0 skipped
```

## MCP server

Lets an agent check its own context before acting. One read-only tool:
`check_docs(paths, include_ok=false, scope=null)`.

    claude mcp add --scope user driftcheck -- uvx --from "driftcheck[mcp]" driftcheck-mcp

## Forgejo configuration

Repo claims use `$FORGEJO_URL` (default `http://127.0.0.1:3000`). The token is
read from `$FORGEJO_TOKEN` or `~/.config/forgejo-token.env`, sent only to that
URL and never printed. Without a token, private repos report as not found.

## Design decisions

- **Deterministic over clever.** Checks are plain probes (stat, connect,
  `systemctl`, one API call). An LLM can read the report; it should not
  produce it.
- **Never cry wolf.** A tool that raises false alarms gets ignored. Anything
  it cannot judge reliably is `unverifiable`, not `drift`. A path like
  `/user/tokens/verify` (an API route, no such top-level directory) is
  `unverifiable`; a missing file under a real directory is `drift`.
- **Scope is explicit.** Claims that are true on another machine are tagged,
  not guessed at.

## Limitations

Repo claims work against Forgejo only (not GitHub or GitLab yet). Branch and flag claims are not checked, and prose such as "the forge also
holds X, Y, Z" is not parsed. Only the claim forms in the table above are
extracted.

## Development

    uv run python -m unittest discover -s tests

MIT licensed.
