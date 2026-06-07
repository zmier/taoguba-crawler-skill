# TASK11：反爬检测、熔断与保守限速

## 背景

TASK10 第一批出现疑似风控：帖子详情请求返回 200，但 HTML 是 `错误页面_淘股吧`。如果不检测，会把错误页当成空详情并标记 done。

当前应暂停 live 抓取，先补保护机制。

## 目标

- 识别淘股吧错误页、访问过频页、异常结构页。
- full/trial/batch 遇到 blocked 页面立即熔断。
- 不把错误页写成详情。
- 不把 blocked article 标记为 done。
- 提供保守限速默认值。

## 已完成

- `common/tgb_guard.py`
  - `GuardDecision`
  - `AntiBotBlocked`
  - `ConservativeCrawlPolicy`
  - `classify_tgb_page()`
  - `require_normal_page()`
- `common/tgb_full.py` 已接入 guard。
- 单元测试：`tests/unit/test_guard.py`
- e2e 测试：`tests/e2e/test_full_guard.py`

## 熔断规则

出现以下情况应立即停止当前 batch：

- 页面标题为 `错误页面_淘股吧`。
- 页面包含访问太频繁、稍后再试等提示。
- 详情页缺少标题、正文和评论等关键结构。

## 恢复建议

- 冷却 30-60 分钟或更久。
- 先用浏览器确认能正常访问帖子。
- 恢复后使用保守参数：

```text
request_interval_seconds = 10
max_list_pages_per_batch = 1
max_articles_per_page = 5
max_comment_pages_per_article = 1
cooldown_minutes_on_block = 60
```

## 当前状态

- TASK11 已完成 MVP。
- 当前不建议继续 TASK10 live 抓取，直到浏览器访问恢复。
