# TASK13：批次运行台账与保守 full

## 目标

在 TASK11 熔断保护后，用保守参数恢复 TASK10 full batch，并记录每一批运行结果。

## 当前批次参数

```text
max_list_pages = 1
max_articles_per_page = 3
max_comment_pages = 1
interval = 10.0
db = data/tgb-full.sqlite
```

## 验收标准

- `failures = 0`
- `empty_detail_articles = 0`
- `comments_seen > 0`
- `full_run_gate = manual_approval_granted`
- 每批结果写入 `tasks/TASK13-batch-ledger/outputs/batch-ledger.md`
