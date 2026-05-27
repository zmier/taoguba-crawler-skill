# full/backfill 设计

## 核心策略

full/backfill 与 incremental 的方向相反。

- incremental：从 `/bbs/1/1` 开始，关注最新帖子和近期评论变化。
- backfill：从 `/bbs/{total_pages}/1` 开始，倒序回填历史老帖子。

原因：

- 老页面更稳定，评论继续增长的概率低。
- 倒序回填更适合长期归档。
- 最新页交给 incremental，不和 backfill 混在一起。

## TASK07 拆分

| 子任务 | 名称 | 说明 |
| --- | --- | --- |
| TASK07A | full/backfill 设计文档 | 定义方向、范围、闸门 |
| TASK07B | 评论分页补全 | 根据 `comment_page_count` 抓 `/a/{slug}-2` 等后续页 |
| TASK07C | 倒序列表页队列 | 从 `total_pages` 向前规划列表页 |
| TASK07D | backfill sample 命令 | 提供小样本命令，不长期运行 |
| TASK07E | full UAT 与运行闸门 | 明确 full 前必须人工确认 |

## 数据策略

- 列表索引写入 `articles`。
- 详情正文写入 `articles.main_text/main_html`。
- 评论写入 `comments`，按 `(article_slug, reply_id)` 幂等。
- 评论页抓取记录写入 `article_pages`。
- 失败记录写入 `failures`。

## sample 限制

backfill sample 默认限制：

```text
max_list_pages = 2
max_articles_per_page = 3
max_comment_pages_per_article = 2
```

这些限制是运行闸门，避免 sample 变成 full。

## full 前待补

- 完整 list/comment/page 队列化。
- 每日运行报告。
- 磁盘预算。
- 图片下载策略。
- 失败重试审计。
- 用户手动确认。
