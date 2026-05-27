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

