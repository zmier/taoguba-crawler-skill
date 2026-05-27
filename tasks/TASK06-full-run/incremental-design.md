# TASK06 incremental 增量模式设计

## 1. 阶段定位

incremental 是 sample 之后、full 之前的运行阶段。

它不负责全量历史回填，也不从最后一页倒序扫全站。它负责每天或每次启动时，从最新列表页开始发现新增帖子，并复查近期可能继续增长评论的帖子。

阶段顺序：

```text
sample 小闭环已完成 -> incremental 增量模式 -> full 倒序历史回填
```

## 2. 核心困惑与决策

### 2.1 列表总页数

全量历史回填需要知道当前论坛列表总页数，例如当前观察到的最后页形态：

```text
https://www.tgb.cn/bbs/92757/1
```

incremental 阶段也应实现总页数解析，但只作为分页边界能力，不立即触发 full 全量抓取。

### 2.2 新旧页面策略不同

- 最新页 `/bbs/1/1`：帖子和评论仍会变化，适合增量发现与近期复查。
- 历史末页 `/bbs/{total_pages}/1`：老帖子更稳定，适合后续 full 倒序回填。

因此：

- incremental：从最新页开始正向扫描少量页。
- full/backfill：从最后页开始倒序扫描历史页。

### 2.3 评论复查

只发现新帖不够。近期帖子可能继续新增评论，因此 incremental 要额外复查近期帖子评论。

复查候选：

- 列表页 `reply_count` 大于数据库已存评论数的帖子。
- 最近 N 天发现或抓取过的帖子。
- 详情已抓但评论页未抓完的帖子。
- 上次失败但未超过最大重试次数的帖子。

## 3. incremental 子 TASK 拆分

建议拆成 5 个子 TASK，都归属 TASK06。

| 子任务 | 名称 | 目标 | 主要产物 | 状态 |
| --- | --- | --- | --- | --- |
| TASK06A | 列表总页数与分页边界 | 从列表页解析总页数，确认最新页/最后页边界 | `parse_bbs_pagination()`、单测、边界 fixture | 未开始 |
| TASK06B | 增量新帖发现 | 从 `/bbs/1/1` 起扫描少量页，新增帖子入库并入队详情 | incremental discovery runner、e2e | 未开始 |
| TASK06C | 停止条件 | 连续已知帖子或连续无新增页达到阈值即停止 | stop policy、单测 | 未开始 |
| TASK06D | 近期评论复查 | 对 reply_count 变化、近期帖子、未完成评论页进行复查 | refresh planner、e2e/UAT | 未开始 |
| TASK06E | incremental 命令与验收 | 提供 `make crawl-incremental` 和验收摘要 | CLI、Makefile target、UAT | 未开始 |

当前实现状态：

| 子任务 | 状态 | 已完成产物 |
| --- | --- | --- |
| TASK06A | 已完成 | `common.tgb_index.parse_bbs_pagination()`、`build_bbs_page_url()`、分页单测 |
| TASK06B | 已完成 | `common.tgb_incremental.run_incremental()` 新帖发现与详情入队 |
| TASK06C | 已完成 | `StopPolicy`、`IncrementalScanState`、`should_stop_incremental()` |
| TASK06D | 已完成 | `find_comment_refresh_candidates()` 与 runner 评论复查步骤 |
| TASK06E | 已完成 | `scripts/tgb_incremental.py`、`make crawl-incremental`、e2e/UAT |

## 4. 子 TASK 细化

### TASK06A：列表总页数与分页边界

目标：

- 从 `/bbs/1/1` 或任意列表页 HTML 解析总页数。
- 明确当前最新页为 `1`，最后页为 `total_pages`。
- 验证 `/bbs/{total_pages}/1` 可解析，最后一条记录接近当前可见最早帖子。

测试：

- unit：给定列表 fixture，能解析 page_no 和 total_pages。
- integration：live 小验证可读取 `/bbs/1/1` 的 total_pages，再请求 `/bbs/{total_pages}/1` 解析列表记录。

完成标准：

- 能自动生成最新页 URL 和最后页 URL。
- 不依赖人工填写 `92757` 这类页码。

### TASK06B：增量新帖发现

目标：

- 从 `/bbs/1/1` 开始扫描。
- 发现数据库不存在的 slug 时，写入 `articles` 索引字段，并把详情 URL 入队。
- 对已存在但列表计数变化的帖子，更新索引字段。

测试：

- e2e：用两个列表 fixture 模拟“旧库 + 新列表”，只新增新 slug。
- unit：同一 slug 重复出现时不重复入队。

完成标准：

- 新帖子可入库、入队。
- 已知帖子不重复抓详情。

### TASK06C：停止条件

目标：

避免 incremental 无限向历史页扫描。

建议停止条件：

- 连续 `known_article_threshold` 条帖子已抓详情且无列表计数变化。
- 或连续 `no_new_page_threshold` 页没有新增帖子。
- 或达到 `max_pages` 安全上限。

默认建议：

```text
known_article_threshold = 50
no_new_page_threshold = 2
max_pages = 5
```

测试：

- unit：输入模拟扫描结果，判断是否停止。
- e2e：扫描 fixture 页时能在阈值触发后停下。

完成标准：

- incremental 可短时间完成。
- 不会误触发 full 历史回填。

### TASK06D：近期评论复查

目标：

让近期帖子评论不会漏。

候选规则：

- `reply_count > comments_count` 的帖子优先复查。
- `fetched_at` 或 `updated_at` 在最近 N 天内的帖子复查。
- `comment_page_count` 大于已抓评论页数的帖子继续补页。
- `failures` 中可重试任务回到队列。

默认建议：

```text
recent_days = 7
max_refresh_articles = 20
comment_pages_per_article = 1 起步，后续按 comment_page_count 扩展
```

测试：

- integration：构造数据库状态，能选出 reply_count 变化的帖子。
- e2e：live UAT 至少抓到一篇 `reply_count > 0` 的帖子并写入评论。

完成标准：

- 近期有评论变化的帖子会被重新抓评论。
- 评论 upsert 幂等，不重复产生评论。

### TASK06E：incremental 命令与验收

目标：

提供可运行入口和验收摘要。

命令：

```bash
make crawl-incremental
```

或：

```bash
../../.venv/bin/python scripts/tgb_incremental.py --max-pages 5 --max-articles 20
```

summary 字段建议：

- `mode = incremental`
- `full_run = false`
- `list_pages_scanned`
- `index_records_seen`
- `new_articles`
- `updated_articles`
- `article_details_fetched`
- `comment_refresh_candidates`
- `comments_saved`
- `queue_done`
- `failures`
- `stop_reason`

完成标准：

- 命令可跑通。
- 输出摘要清楚说明不是 full。
- UAT 覆盖新增帖、已知帖停止、评论复查三类行为。

## 5. 与 full/backfill 的边界

incremental 不做：

- 不从 `/bbs/{total_pages}/1` 倒序抓完整历史。
- 不长期扫描全部列表页。
- 不默认下载图片二进制。

full/backfill 后续应做：

- 从 `total_pages` 倒序到 `1`。
- 优先抓老页面，因为老帖子和评论更稳定。
- 使用 TASK05 队列断点续爬。
- 配置更严格限速和长期运行日志。

## 6. 推荐推进顺序

1. TASK06A：总页数与分页边界。
2. TASK06B：新帖发现。
3. TASK06C：停止条件。
4. TASK06D：近期评论复查。
5. TASK06E：命令与验收。

实现顺序建议串行推进。TASK06D 的 UAT 可以提前准备，但应等 TASK06B/C 的队列与停止条件稳定后再实现。

## 7. 当前结论

incremental 阶段已完成 MVP，不启动 full 全量抓取。

sample 已完成并通过 live 评论入库补验收；incremental 已具备分页边界解析、新帖发现、停止条件、近期评论复查、命令入口和验收摘要。下一步才是 full/backfill 的倒序历史回填设计。
