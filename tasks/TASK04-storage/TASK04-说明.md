# TASK04：SQLite 存储

## 目标

建立结构化存储层，支持 upsert、去重、状态查询。

## 输入

- TASK01/TASK02/TASK03 的结构化记录模型

## 输出

- `data/tgb.sqlite`
- `articles`、`article_pages`、`comments`、`crawl_queue`、`failures` 表

## 完成标准

- 建表、插入、重复插入、状态更新测试通过。
- e2e 小样本可写出完整数据库。

## 当前状态

- MVP：已完成。
- 已新增 `common/tgb_storage.py`，提供 SQLite 连接、建表、索引/详情/评论 upsert、基础查询与计数。
- Schema 已包含 `articles`、`article_pages`、`comments`、`crawl_queue`、`failures`。
- 已新增 `tests/unit/test_storage.py`，覆盖建表、索引记录幂等写入、详情补充、评论幂等写入。

## 验证命令

```bash
../../.venv/bin/python -m unittest tests.unit.test_storage
```
