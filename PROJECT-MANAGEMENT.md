# TGB 全量爬虫项目管理文档

## 1. 项目目标

本项目目标是构建一个可长期运行、可断点续爬、可验证的淘股吧论坛数据采集系统。

当前阶段目标聚焦于：

- 全量论坛帖子索引
- 每篇帖子详情
- 每篇帖子全量评论
- 结构化存储
- 可复跑、可测试、可审计的开发过程

暂不优先覆盖：

- 说说、视频、直播、投资策略等非论坛模块
- 图片二进制全量下载
- LLM 复盘自动推送链路

## 2. 当前基础

已有项目能力：

- `scripts/crawler_bbs.py` 能抓论坛列表页。
- `scripts/crawler_home.py` 能抓首页推荐 API。
- `get_article_content()` 能解析主帖、主帖图片、楼主回复。
- `.env` 已支持淘股吧登录 Cookie。
- 当前请求方式是 `requests + BeautifulSoup`，与页面服务端渲染特征一致。

已验证事实：

- `https://www.tgb.cn/bbs/1/1` 可抓取帖子列表。
- `https://www.tgb.cn/a/{slug}` 可抓取帖子详情 HTML。
- 评论区在详情页 HTML 中以 `.comment-data` 渲染。
- 评论分页形态预计为 `https://www.tgb.cn/a/{slug}-{page}`，开发时需用测试固化。

## 3. 目标架构

建议逐步演进为以下结构：

```text
tgb/
  PROJECT-MANAGEMENT.md
  README.md
  log.md
  .env
  main.py
  app_common.py
  scripts/                 # 现有脚本，保留兼容
  common/                  # 新增：可复用基础能力
  tests/
    unit/
    integration/
    e2e/
    uat/
    fixtures/
  tasks/
    TASK01-index-crawl/
    TASK02-article-parse/
    TASK03-comment-parse/
    TASK04-storage/
    TASK05-resume-and-retry/
    TASK06-full-run/
  data/
    tgb.sqlite
  output/
  logs/
  state/
```

说明：

- `scripts/` 保留现有入口，避免一次性重构。
- `common/` 只放跨任务复用代码，例如请求、解析、存储、限速。
- `tasks/` 记录阶段性实现，每个任务有独立说明、输入、输出和日志。
- `tests/` 承载 TDD/BDD 测试，包含 unit、integration、e2e、UAT 四层。
- `data/tgb.sqlite` 作为第一阶段结构化存储。

### 3.1 TASK 文件夹管理规则

每个 TASK 使用独立文件夹管理：

```text
tasks/TASKxx-name/
  TASKxx-说明.md
  inputs/
  outputs/
  cache/
  logs/
```

各目录职责：

- `TASKxx-说明.md`：任务目标、输入、输出、完成标准、人审点。
- `inputs/`：该任务专属输入样本或人工准备材料。
- `outputs/`：该任务阶段性产物，不等于最终交付。
- `cache/`：临时缓存，可清理。
- `logs/`：任务局部运行日志。

共享生产代码不直接放在 TASK 文件夹里。探索代码可以先放在 TASK 文件夹；一旦稳定并被多个任务依赖，应迁移到 `common/` 或 `scripts/`，并补测试。

## 4. 任务拆分

### 4.1 TASK 总览

| TASK | 名称 | 主要产物 | 依赖 | 是否可并行 |
| --- | --- | --- | --- | --- |
| TASK01 | 全量帖子索引 | 列表解析器、索引抓取器、帖子索引数据 | 无 | 可先行，最高优先级 |
| TASK02 | 帖子详情解析 | 详情解析器、主帖结构化数据 | TASK01 的 URL 样本 | 可与 TASK04 部分并行 |
| TASK03 | 全量评论解析 | 评论解析器、评论分页抓取器 | TASK02 的详情页样本 | 可与 TASK04 部分并行 |
| TASK04 | SQLite 存储 | schema、upsert、查询接口 | TASK01 字段定义 | 可与 TASK02/TASK03 并行 |
| TASK05 | 断点续爬与重试 | 队列状态、失败重试、限速策略 | TASK01-04 | 不建议提前并行 |
| TASK06 | 运行模式与验收 | sample/incremental/full 命令、UAT 报告 | TASK01-05 | 不建议提前并行 |

### 4.1.1 当前进度

| TASK | 状态 | 已完成产物 |
| --- | --- | --- |
| TASK01 | MVP 完成 | `common/tgb_index.py`、列表页 fixture、索引解析单测、旧脚本兼容 |
| TASK02 | MVP 完成 | `common/tgb_article.py`、详情页 fixture、主帖解析单测、旧脚本兼容 |
| TASK03 | MVP 完成 | `common/tgb_comment.py`、评论解析单测、评论分页 URL 规则 |
| TASK04 | MVP 完成 | `common/tgb_storage.py`、SQLite schema、结构化 upsert 单测 |
| TASK05 | MVP 完成 | `common/tgb_resume.py`、可恢复队列、失败重试与退避单测 |
| TASK06 | sample 完成 | `common/tgb_sample.py`、`scripts/tgb_sample.py`、sample e2e/UAT、`Makefile` |

### 4.2 依赖关系

```text
TASK01 全量帖子索引
  ├── TASK02 帖子详情解析
  │     └── TASK03 全量评论解析
  └── TASK04 SQLite 存储
        └── TASK05 断点续爬与重试
              └── TASK06 运行模式与验收
```

更准确地说：

- TASK01 是入口任务，必须最先做。没有稳定索引，就没有可靠 URL 队列。
- TASK02 依赖 TASK01 产出的帖子 URL，但可以用固定样例 URL 提前开发。
- TASK03 依赖 TASK02 对详情页结构和评论分页规则的确认，但评论解析函数可以用 fixture 提前开发。
- TASK04 只依赖字段设计，不强依赖真实爬取完成，因此可以和 TASK02/TASK03 并行。
- TASK05 必须等索引、详情、评论、存储的基本接口稳定后再做，否则队列状态会反复改。
- TASK06 是验收层，应该在前五项能跑通后再做。

### 4.3 推荐执行批次

#### Batch A：先打地基，串行

- TASK01 全量帖子索引

理由：

- 它决定后续 URL 队列、去重键、增量逻辑和全量页码策略。
- 当前已有 `crawler_bbs.crawl_articles()`，适合先用 TDD 抽成稳定解析器。

#### Batch B：可并行开发

- TASK02 帖子详情解析
- TASK04 SQLite 存储

理由：

- TASK02 可以基于固定详情页 fixture 开发。
- TASK04 可以先按 TASK01/TASK02/TASK03 的目标字段设计 schema。
- 二者交汇点是字段命名和 upsert 接口，需要在开发前约定数据模型。

#### Batch C：半并行，但要等分页规则确认

- TASK03 全量评论解析

理由：

- 评论块解析可以和 TASK02 并行。
- 评论分页抓取必须等 TASK02 确认详情页里的总页数、分页 URL 和边界情况。

#### Batch D：后置串行

- TASK05 断点续爬与重试
- TASK06 运行模式与验收

理由：

- 这两项属于调度和运行层，依赖前面模块接口稳定。
- 过早实现会造成大量返工。

### 4.4 并行开发边界

可以并行：

- 详情页 fixture 收集与 TASK04 schema 设计。
- 评论 parser 测试与 SQLite 表结构测试。
- UAT 验收清单编写与前面实现并行。

不建议并行：

- 在 TASK01 未定型前实现全量调度。
- 在 TASK03 未定型前实现评论队列状态。
- 在 TASK04 未定型前实现断点续爬。

并行时必须遵守：

- 所有字段模型变更先更新测试和文档。
- 任一 TASK 产出被其他 TASK 依赖时，必须补 e2e fixture。
- 每次实际开发前后都要更新 `log.md`。

### TASK01：全量帖子索引

目标：

- 遍历 `https://www.tgb.cn/bbs/{page}/1`。
- 提取帖子 URL、slug、标题、作者、作者 ID、评论数、浏览数、发帖时间、回帖时间、列表页码。
- 支持起止页参数，先以小样本页数测试。

完成标准：

- 给定 1-3 页列表 fixture，能稳定解析索引。
- 真实抓取前 3 页能写入 SQLite。
- 重复抓取不会产生重复帖子。

### TASK02：帖子详情解析

目标：

- 抓取 `/a/{slug}`。
- 解析标题、主帖作者、作者 ID、发布时间、浏览数、评论数、主帖正文、主帖 HTML、图片 URL。

完成标准：

- fixture 覆盖普通图文帖、有图帖、无评论帖。
- 真实抓取一篇样例帖能落库。

### TASK03：全量评论解析

目标：

- 解析 `.comment-data`。
- 抽取 reply_id、user_id、username、是否楼主、楼层、发布时间、正文、HTML、图片 URL、引用信息。
- 支持评论分页 `/a/{slug}-{page}`。

完成标准：

- fixture 覆盖普通评论、楼主评论、带图评论、引用评论。
- 给定总页数时能抓完全部评论页。
- 同一 reply_id 重复写入时幂等。

### TASK04：SQLite 存储

目标：

- 建立 `articles`、`article_pages`、`comments`、`crawl_queue`、`failures` 表。
- 支持 upsert。
- 支持查询未抓详情、未抓评论、失败重试队列。

完成标准：

- 单元测试覆盖建表、插入、重复插入、状态更新。
- e2e 测试能从小样本 HTML 写出完整数据库。

### TASK05：断点续爬、限速与重试

目标：

- 记录列表页进度、详情页状态、评论页状态。
- 支持失败 URL 重试。
- 支持请求间隔、指数退避和最大失败次数。

完成标准：

- 中断后重跑能从未完成任务继续。
- 网络失败不会丢失已完成结果。

### TASK06：全量运行与验收

目标：

- 提供命令行入口。
- 支持小样本、增量、全量三种模式。
- 输出运行摘要。

推进顺序：

1. 先实现 `sample` 小样本闭环：抓少量列表页、少量详情页和评论第一页，写入 SQLite，并验证重复运行幂等。
2. `sample` 通过后，再实现 `incremental` 增量模式：从最新列表页开始，只抓新增或变化帖子。
3. `incremental` 稳定后，最后进入 `full` 全量模式：按页码范围持续抓取，并依赖 TASK05 的断点续爬与重试机制。

阶段闸门：

- `sample` 未通过前，不启动全量历史页抓取。
- `incremental` 未通过前，不做长期运行。
- `full` 运行前必须有 UAT 清单、限速参数、失败重试策略和中断恢复验证。

完成标准：

- `sample` 模式可在数分钟内完成。
- `incremental` 模式只抓新增或变化内容。
- `full` 模式可长期运行，日志和状态可审计。

当前进度：

- `sample`：已完成。支持 fixture e2e/UAT 和真实小样本命令。
- `incremental`：未开始。
- `full`：未开始。

## 5. TDD-BDD 开发约定

所有实现型任务遵循红-绿-重构：

1. **Red**：先写失败测试，明确预期行为。
2. **Green**：写最小实现让测试通过。
3. **Refactor**：在测试保持通过的前提下清理结构。

测试分四层：

- `tests/unit/`：解析函数、URL 规则、存储函数等小单元。
- `tests/integration/`：模块边界测试，例如 parser + storage、request + parser、queue + storage。
- `tests/e2e/`：用 fixture HTML/API 样本串起列表、详情、评论、存储的小型完整流程。
- `tests/uat/`：用户验收测试，检查输出文件、字段完整度、运行摘要、断点续爬行为。
- `tests/fixtures/`：稳定 HTML/JSON 样本，不写测试逻辑。

测试代码必须使用中文 GIVEN-WHEN-THEN 注释：

```python
def test_parse_comment_with_author_badge():
    # GIVEN：一段包含“楼主”标识的评论 HTML
    html = load_fixture("comment_author.html")

    # WHEN：解析评论块
    comment = parse_comment(html)

    # THEN：应识别为楼主评论并返回 reply_id
    assert comment.is_author is True
    assert comment.reply_id
```

不允许先写大段实现再补测试。若遇到探索性质代码，应先放在临时脚本或 notebook，确认规则后再通过测试固化。

## 6. ReAct 开发日志约定

所有实质性开发步骤必须记录到 `log.md`。

每一步遵循以下顺序：

1. **Observation**：先记录观察到的事实、上下文、文件状态或测试结果。
2. **Plan**：记录下一步要做什么，以及为什么这么做。
3. **Action**：执行实际操作，例如写测试、改代码、运行命令。
4. **Result**：操作后回填结果，包括通过、失败、错误信息、生成文件。
5. **Reflection**：必要时记录下一步调整或风险。

模板：

```markdown
## YYYY-MM-DD HH:MM - TASKxx 简短标题

### Observation
- ...

### Plan
- ...

### Action
- ...

### Result
- ...

### Reflection
- ...
```

规则：

- Action 前必须先有 Observation 和 Plan。
- Result 必须在操作后回填，不能留空。
- 测试失败也要记录，失败是 Red 阶段的正常产物。
- 重要命令要记录命令名和结论，不必粘贴大段输出。
- 不在 `log.md` 中记录敏感值，例如 Cookie、API Key、密码。

## 7. 数据与存储策略

第一阶段使用 SQLite：

```text
data/tgb.sqlite
```

建议表：

- `articles`：帖子级结构化数据。
- `article_pages`：帖子原始 HTML 页面缓存或页面抓取状态。
- `comments`：评论结构化数据。
- `crawl_queue`：待抓任务。
- `failures`：失败 URL、错误类型、重试次数。

图片策略：

- 默认只存图片 URL。
- 不默认下载全量图片二进制。
- 需要复盘 HTML 时可按需下载或 base64 内嵌。

原始 HTML 策略：

- 小样本和失败样本必须保留 raw HTML，方便回归测试。
- 全量运行时可配置是否保留 raw HTML，避免磁盘膨胀。

## 8. 运行模式

建议命令：

```bash
make test
make crawl-sample
make crawl-incremental
make crawl-full
```

当前已提供 `Makefile`，优先使用 `make` 命令；也可以用 Python 入口直接运行。

模式定义：

- `sample`：抓前 1-3 页列表和少量详情，用于开发验证。
- `incremental`：从最新页开始，只抓新增或更新帖子。
- `full`：从指定页范围持续全量抓取。

推荐执行顺序：

```text
单元稳定 -> sample 小闭环 -> incremental 增量 -> full 全量长期运行
```

当前 `sample 小闭环` 已完成，下一步才考虑 `incremental` 增量模式。

## 9. 风险与约束

- 淘股吧登录态 Cookie 会过期，需要定期从浏览器 profile 刷新。
- 全量历史页数很大，必须限速和断点续爬。
- 页面结构可能变化，解析器必须由 fixture 测试保护。
- 不应在 git 中提交 `.env`、Cookie、API Key、数据库大文件和输出产物。
- 大规模抓取需控制频率，避免对目标站造成压力。

## 10. 近期实施顺序

已完成：

1. 建立 `tests/fixtures/`，保存一页列表 HTML、一页帖子详情 HTML。
2. Red：为列表解析写失败测试。
3. Green：抽出 `parse_bbs_list()` 并通过测试。
4. Red：为评论解析写失败测试。
5. Green：抽出 `parse_comments()` 并通过测试。
6. 建立 SQLite schema 和 upsert 测试。
7. 建立 crawl queue 断点续爬与失败重试测试。

推荐下一步：

1. 进入 TASK06 的 `incremental` 设计。
2. 明确每日新增判定规则、列表页停止条件和已抓帖子复查策略。
3. 增加 incremental 的 integration/e2e/UAT 测试。
4. `incremental` 通过前，不进入 `full` 全量抓取。
