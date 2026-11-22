from __future__ import annotations

import argparse
import json
import sys

from .core import DRIFT, SKIPPED, UNKNOWN, collect, extract, verify


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "timer":
        from .timer import main as timer_main
        return timer_main(argv[1:])
    ap = argparse.ArgumentParser(prog="driftcheck",
        description="Check factual claims in markdown docs against the live system.")
    ap.add_argument("files", nargs="+")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--scope", help="active scope for <!-- driftcheck: scope=X --> claims (default $DRIFTCHECK_SCOPE)")
    ap.add_argument("--all", action="store_true", help="also list ok/unverifiable claims")
    args = ap.parse_args(argv)

    results = []
    for f in collect(args.files):
        with open(f, encoding="utf-8") as fh:
            results += verify(extract(fh.read(), f), args.scope)

    drift = [r for r in results if r.status == DRIFT]
    if args.json:
        json.dump([r.to_dict() for r in results], sys.stdout, indent=2)
        print()
    else:
        shown = results if args.all else drift
        for r in shown:
            c = r.claim
            print(f"{r.status.upper():12} {c.file}:{c.line}  {c.kind} {c.value}  - {r.detail}")
        ok = sum(r.status == "ok" for r in results)
        unk = sum(r.status == UNKNOWN for r in results)
        skp = sum(r.status == SKIPPED for r in results)
        print(f"\n{len(results)} claims: {ok} ok, {len(drift)} drift, {unk} unverifiable, {skp} skipped")
    return 1 if drift else 0


if __name__ == "__main__":
    sys.exit(main())
