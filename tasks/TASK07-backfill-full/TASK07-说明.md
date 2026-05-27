# TASK07：full/backfill 倒序历史回填

## 目标

设计并实现 full/backfill 的最小可验收能力：从论坛最后页开始倒序抓老页面，并补齐每篇帖子的评论分页。

当前阶段只完成 backfill sample，不启动长期 full 全量运行。

## 输入

- TASK01-TASK06 的稳定 parser、storage、queue、incremental 能力
- 列表总页数 `total_pages`
- 最老列表页 `/bbs/{total_pages}/1`

## 输出

- `common/tgb_backfill.py`
- `scripts/tgb_backfill_sample.py`
- `make crawl-backfill-sample`
- backfill sample 运行摘要
- full 运行前闸门

## 子任务

| 子任务 | 名称 | 状态 |
| --- | --- | --- |
| TASK07A | full/backfill 设计文档 | 已完成 |
| TASK07B | 评论分页补全 | 已完成 |
| TASK07C | 倒序列表页队列/规划 | 已完成 |
| TASK07D | backfill sample 命令 | 已完成 |
| TASK07E | full UAT 与运行闸门 | 已完成 |

## 当前实现

- `plan_backfill_pages(total_pages, max_pages)`：从最后页开始倒序规划页码。
- `plan_comment_pages(comment_page_count, max_pages)`：按上限规划评论分页，避免 sample 误跑成 full。
- `run_backfill_sample()`：抓倒序列表页、每页末尾若干帖、每帖若干评论页。
- `scripts/tgb_backfill_sample.py`：命令行入口，默认自动解析 `total_pages`。

## 运行命令

```bash
make crawl-backfill-sample
```

或直接运行：

```bash
../../.venv/bin/python scripts/tgb_backfill_sample.py --max-list-pages 2 --max-articles-per-page 3 --max-comment-pages 2
```

## 验收标准

- `mode` 必须为 `backfill_sample`。
- `full_run` 必须为 `false`。
- `full_run_gate` 必须为 `manual_approval_required`。
- `direction` 必须为 `reverse`。
- 能从 `total_pages` 倒序规划列表页。
- 能抓评论分页，例如第一页和第二页。
- 能输出 `stop_reason`，说明 sample 因限制结束。

## full 运行闸门

backfill sample 完成后，仍不能直接启动长期 full。full 前必须补：

- 更保守限速参数。
- 长期运行日志和进度报表。
- 评论全页抓取上限与磁盘预算。
- 中断恢复演练。
- 用户手动确认。
