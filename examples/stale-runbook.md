# Deploy runbook (stale on purpose)

1. Build with `/tmp/driftcheck-demo/build.sh` (this script was deleted).
2. The app serves on http://127.0.0.1:9 (nothing runs here).
3. Restarts are handled by `old-worker.service`, long since removed.
4. Config sits in `/tmp/driftcheck-demo-config.yaml`.
5. Logs go to `/etc/hostname` (this one still exists, so it passes).
