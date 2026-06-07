# TASK13 批次运行台账

| batch | date | db | total_pages | planned_pages | list_pages_done | articles_indexed | details_fetched | comment_pages | comments_seen | failures | empty_details | db_size | status |
| --- | --- | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| 001 | 2026-05-28 | `data/tgb-full.sqlite` | 92772 | `[92772]` | 1 | 32 | 3 | 3 | 72 | 0 | 0 | 128K | passed |
| 002 | 2026-05-28 | `data/tgb-full.sqlite` | 92772 | `[92771]` | 1 | 70 | 3 | 3 | 13 | 0 | 0 | - | passed |
| 003 | 2026-05-28 | `data/tgb-full.sqlite` | 92772 | `[92770]` | 1 | 70 | 3 | 3 | 29 | 0 | 0 | - | passed |
| 004 | 2026-05-28 | `data/tgb-full.sqlite` | 92772 | `[92769]` | 1 | 70 | 3 | 3 | 12 | 0 | 0 | - | passed |
| 005 | 2026-05-28 | `data/tgb-full.sqlite` | 92772 | `[92768]` | 1 | 70 | 3 | 3 | 1 | 0 | 0 | 576K | passed |
| 006 | 2026-05-28 | `data/tgb-full.sqlite` | 92772 | `[92767]` | 1 | 70 | 5 | 5 | 8 | 0 | 0 | 640K | passed |

## Batch 001 Notes

- 旧 `data/tgb-full.sqlite` 已按用户确认删除后重建。
- 参数：最后 1 页、最多 3 篇、每篇 1 页评论、10 秒间隔。
- 入库详情：
  - `1yktHE5Evio`：600572：关注远期成长想象力，正文长度 629。
  - `1yktHE1XJES`：中国人民银行决定上调存款准备金率，正文长度 141。
  - `1yktHE16WgM`：世界因你而精彩，正文长度 335。
- 未触发 TASK11 熔断。

## Batch 002-005 Notes

- 参数保持不变：每批 1 页、最多 3 篇、每篇 1 页评论、10 秒间隔。
- 页码按倒序推进：92771、92770、92769、92768。
- 四批均未触发 TASK11 熔断，`failures = 0`，`empty_details = 0`。
- 当前累计：
  - `articles = 312`
  - `detail_count = 15`
  - `comments = 127`
  - `article_pages = 15`
  - `queue_done = 35`
  - `db_size = 576K`

## Batch 006 Notes

- 参数小幅放大：`max_articles_per_page` 从 3 提高到 5。
- 其他参数不变：每批 1 页、每篇 1 页评论、10 秒间隔。
- Batch 006 通过，未触发 TASK11 熔断。
- 当前累计：
  - `articles = 382`
  - `detail_count = 20`
  - `comments = 135`
  - `article_pages = 20`
  - `failures = 0`
  - `empty_detail_articles = 0`
  - `db_size = 640K`
