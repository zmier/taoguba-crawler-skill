# TASK02：帖子详情解析

## 状态

已完成 MVP。

## 目标

解析 `/a/{slug}` 的主帖详情。

## 输入

- 帖子详情 HTML fixtures
- TASK01 产出的帖子 URL

## 输出

- 主帖结构化数据：标题、作者、作者 ID、发布时间、浏览数、评论数、正文、HTML、图片 URL。

## 完成标准

- [x] 普通图文帖 fixture 测试通过。
- [x] 真实样例帖解析结果稳定。
- [x] `scripts/crawler_bbs.get_article_content()` 已复用主帖详情 parser。

## 已实现内容

- `common/tgb_article.py`
  - `ArticleDetail`
  - `parse_article_detail()`
- `tests/unit/test_article_parser.py`
- `tests/fixtures/article_detail_2s8aVDvYC5w.html`

## 验证记录

- `../../.venv/bin/python -m unittest tests.unit.test_index_parser tests.unit.test_article_parser`：通过。
- 真实抓取 `https://www.tgb.cn/a/2s8aVDvYC5w`：可解析标题、主帖正文、图片和楼主回复兼容输出。
