# TASK05：断点续爬与重试

## 目标

让全量爬取可中断、可恢复、可重试。

## 输入

- SQLite 队列表
- failures 表
- 抓取配置

## 输出

- 可恢复的列表页、详情页、评论页抓取状态
- 限速与退避策略

## 完成标准

- 中断后重跑不会重复大量工作。
- 失败 URL 可按最大次数重试。

## 当前状态

- MVP：已完成。
- 已新增 `common/tgb_resume.py`，基于 `crawl_queue` 和 `failures` 实现可恢复队列。
- 支持幂等入队、按优先级领取任务、完成标记、失败重试、退避时间、最大失败次数、卡住的 running 任务重置。
- 已新增 `tests/unit/test_resume_queue.py`，覆盖断点续爬状态机的核心行为。

## 验证命令

```bash
../../.venv/bin/python -m unittest tests.unit.test_resume_queue
```
