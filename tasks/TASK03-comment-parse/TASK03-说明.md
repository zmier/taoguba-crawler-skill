# TASK03：全量评论解析

## 目标

解析帖子所有评论，并支持评论分页。

## 输入

- 评论区 HTML fixtures
- `/a/{slug}` 与 `/a/{slug}-{page}` 页面

## 输出

- 评论结构化数据：reply_id、user_id、username、is_author、floor、created_at、text、html、image_urls、quote 信息。

## 完成标准

- 普通评论、楼主评论、带图评论、引用评论测试通过。
- 多页评论抓取可幂等落库。

## 当前状态

- MVP：已完成。
- 已新增 `common/tgb_comment.py`，支持评论记录解析和分页 URL 构造。
- 已新增 `tests/unit/test_comment_parser.py`，覆盖普通评论、楼主评论、评论时间、楼层、图片字段和分页 URL。
- 已让 `scripts/crawler_bbs.py` 复用评论 parser，同时保持旧版 HTML 报告只追加楼主回复的兼容行为。

## 验证命令

```bash
../../.venv/bin/python -m unittest tests.unit.test_comment_parser
../../.venv/bin/python -m unittest tests.unit.test_index_parser tests.unit.test_article_parser tests.unit.test_comment_parser
```
