# TASK08：full 运行前审计与参数定稿

## 目标

在进入受控 full 试运行前，明确 full 参数、运行闸门、队列化策略和报告字段。

本任务不启动长期 full。

## 已完成

- `FullRunConfig`：full/trial 参数模型。
- `validate_full_config()`：阻止未人工批准的 production full。
- `plan_full_pages()`：从 `start_page` 到 `end_page` 倒序规划页码。
- `enqueue_full_trial_plan()`：将列表页作为 `list_page` 任务入队。
- `build_full_run_report()`：保留 `manual_approval_required` 闸门。

## 默认参数建议

```text
direction = reverse
start_page = total_pages
end_page = 1
max_list_pages_per_run = 10
max_articles_per_page = 20
max_comment_pages_per_article = 5
request_interval_seconds = 1.0
max_attempts = 3
production_full = false
manual_approval = false
```

## 运行闸门

production full 必须满足：

- `production_full = true`
- `manual_approval = true`
- 已完成 TASK09 受控试运行审核

当前只允许 TASK09 full trial。
