# TASK06：运行模式与验收

## 目标

提供 sample、incremental、full 三种运行模式，并完成用户验收。

## 输入

- TASK01-05 的稳定接口

## 输出

- 可运行命令
- 运行摘要
- UAT 验收记录

## 完成标准

- sample 模式快速跑通。
- incremental 模式能抓每日新增。
- full 模式支持长期全量运行。

## 当前状态

- sample 阶段：已完成。
- incremental 阶段：未开始。
- full 阶段：未开始。

## sample 阶段范围

sample 只做小闭环，不做全量历史页抓取：

- 抓 1 页或少量列表页。
- 入队少量帖子详情 URL。
- 抓少量详情页和评论第一页。
- 写入 SQLite。
- 验证重复写入幂等、队列任务可标记完成、失败会进入 `failures`。

## 已完成产物

- `common/tgb_sample.py`：sample 小闭环 runner。
- `scripts/tgb_sample.py`：命令行入口。
- `tests/e2e/test_sample_runner.py`：fixture 驱动的小闭环 e2e 测试。
- `tests/uat/test_sample_acceptance.py`：sample 验收摘要测试。
- `Makefile`：固定测试与 sample 运行命令。

## 运行命令

```bash
make test
make crawl-sample
```

或直接运行：

```bash
../../.venv/bin/python scripts/tgb_sample.py --list-pages 1 --max-articles 3 --comment-pages 1
```

## sample 验收标准

- `mode` 必须为 `sample`。
- `full_run` 必须为 `false`。
- `list_pages_fetched`、`article_details_fetched`、`comment_pages_fetched`、`comments_saved` 必须有明确计数。
- 数据库文件必须生成。
- sample 通过前不进入 full 全量抓取。
