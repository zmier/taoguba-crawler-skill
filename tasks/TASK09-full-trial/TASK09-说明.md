# TASK09：受控 full 试运行

## 目标

按 TASK08 参数执行一个受控区间试运行，用真实队列流程验证 full/backfill 的长期运行能力。

这不是 TASK10 长期 full。

## 已完成

- `common/tgb_full.py`：受控 full trial runner。
- `scripts/tgb_full_trial.py`：命令行入口。
- `make crawl-full-trial`：固定命令。
- unit/e2e/UAT 测试。

## 队列化流程

1. `list_page`：倒序列表页任务。
2. `article`：详情页任务。
3. `comment_page`：评论分页任务。

评论第一页与详情页 URL 相同，因此队列中使用 `#comment-page-1` 作为逻辑 URL，实际请求时去掉 fragment。

## 运行命令

```bash
make crawl-full-trial
```

或直接运行小范围试跑：

```bash
../../.venv/bin/python scripts/tgb_full_trial.py --max-list-pages 1 --max-articles-per-page 1 --max-comment-pages 2
```

## 验收字段

- `mode = full_trial`
- `full_run = false`
- `full_run_gate = manual_approval_required`
- `direction = reverse`
- `list_page_tasks_enqueued`
- `list_pages_done`
- `article_details_fetched`
- `comment_pages_fetched`
- `queue_done`
- `failures`
- `estimated_remaining_pages`
- `stop_reason`

## TASK10 前置条件

- 审核 TASK09 的真实试运行数据。
- 失败率可接受。
- 评论分页入库符合预期。
- SQLite 体积增长可接受。
- 用户明确批准长期 full。
