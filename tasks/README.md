# Tasks

Each TASK folder is a managed development stage.

Use this layout:

```text
TASKxx-name/
  TASKxx-说明.md
  inputs/
  outputs/
  cache/
  logs/
```

Do not put shared production code directly inside TASK folders. Once an experiment becomes reusable, move it to `common/` or `scripts/`, then protect it with tests.

Current later stages:

- `TASK06-full-run/`: sample and incremental modes.
- `TASK07-backfill-full/`: backfill sample and full-run gate.
- `TASK08-full-preflight/`: full parameters, gates, and report contract.
- `TASK09-full-trial/`: controlled full trial.
- `TASK10-full-production/`: long-running production full, not started.
