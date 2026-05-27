# TASK01：全量帖子索引

## 状态

已完成 MVP。

## 目标

抽出稳定的论坛列表页解析与索引抓取能力。

## 输入

- `https://www.tgb.cn/bbs/{page}/1`
- `https://www.tgb.cn/bbs/{page}/0`
- 列表页 HTML fixtures

## 输出

- 帖子索引记录：slug、url、title、author、author_id、reply_count、view_count、post_time、last_reply_time、source_page。

## 完成标准

- [x] 先写失败测试。
- [x] fixture 列表页解析测试通过。
- [x] 小样本真实抓取 1 页可用。
- [x] 保持 `scripts/crawler_bbs.crawl_articles()` 旧字段兼容。

## 已实现内容

- `common/tgb_index.py`
  - `BbsIndexRecord`
  - `parse_bbs_list()`
  - `to_legacy_article()`
- `tests/unit/test_index_parser.py`
- `tests/fixtures/bbs_list_page_1.html`

## 验证记录

- `../../.venv/bin/python -m unittest tests.unit.test_index_parser`：通过。
- `../../.venv/bin/python -m py_compile common/tgb_index.py scripts/crawler_bbs.py`：通过。
- 真实抓取 `https://www.tgb.cn/bbs/1/1`：可返回帖子列表，旧接口仍输出 `title/url/href`。

## 后续交接

- TASK02 可使用 `BbsIndexRecord.url` 作为详情页输入。
- TASK04 可基于 `BbsIndexRecord` 字段设计 `articles` 表索引字段。
