# TGB 开发日志

本文件记录项目开发过程中的 ReAct 流水账。每个实质性步骤都应先记录观察与计划，再执行操作，最后回填结果。

## 2026-05-27 11:26 - PROJECT 管理约定初始化

### Observation
- 项目当前已有 `scripts/crawler_bbs.py`、`scripts/crawler_home.py`、`scripts/taoguba_report.py` 等脚本。
- 已验证淘股吧登录 Cookie 可用，论坛列表、首页 API、帖子详情解析均可运行。
- 用户要求后续开发遵循 TDD-BDD、红-绿-重构，并以 ReAct 范式记录每一步。

### Plan
- 新增 `PROJECT-MANAGEMENT.md`，明确全量帖子与全量评论爬取的任务拆分、测试策略、存储策略和开发纪律。
- 新增 `log.md`，作为后续开发过程记录文件。
- 本次只建立项目管理约定，不改动爬虫功能代码。

### Action
- 创建 `PROJECT-MANAGEMENT.md`。
- 创建 `log.md` 并写入本次初始化记录。

### Result
- 已建立项目管理文档和 ReAct 开发日志文件。
- 文档中包含 TDD-BDD、GIVEN-WHEN-THEN 中文注释、ReAct 记录顺序、SQLite 存储建议和六个任务阶段。

### Reflection
- 下一步应从 TASK01 开始，以失败测试驱动抽出列表页解析函数。

## 2026-05-27 11:31 - TASK 拆分与并行关系更新

### Observation
- 用户询问当前建议的 TASK 拆分是否可以并行。
- 现有文档已有六个任务阶段，但尚未明确任务之间的依赖关系和并行开发边界。

### Plan
- 更新 `PROJECT-MANAGEMENT.md` 的任务拆分部分。
- 增加任务依赖图、并行性判断和推荐执行批次。
- 保持现有六个 TASK 不变，只补充管理信息。

### Action
- 修改 `PROJECT-MANAGEMENT.md`，加入 TASK 总览表、依赖关系和并行策略。

### Result
- 已更新 `PROJECT-MANAGEMENT.md`。
- 新增 TASK 总览表、依赖关系图、推荐执行批次和并行开发边界。
- 明确 TASK01 必须优先，TASK02/TASK04 可部分并行，TASK05/TASK06 后置串行。

### Reflection
- 后续进入 TASK01 时，应先补列表页 fixture 和失败测试。

## 2026-05-27 11:35 - TASK 文件夹与测试层级补充

### Observation
- 用户确认逐个 TASK 推进，并询问每个 TASK 是否应创建独立文件夹管理。
- 当前 `PROJECT-MANAGEMENT.md` 已描述 `tasks/` 结构，但项目目录尚未创建 TASK 文件夹骨架。
- 当前测试策略包含 unit/e2e/UAT，但未单独列出 integration 测试层。

### Plan
- 创建 `tasks/TASK01-*` 到 `TASK06-*` 的任务文件夹骨架。
- 创建 `tests/unit`、`tests/integration`、`tests/e2e`、`tests/uat`、`tests/fixtures` 测试目录骨架。
- 更新 `PROJECT-MANAGEMENT.md`，明确每个 TASK 文件夹如何管理，并补充 integration 测试层。
- 为每个 TASK 写一个轻量 `TASKxx-说明.md`，先作为管理入口，不进入功能实现。

### Action
- 准备创建任务目录、测试目录和说明文件。

### Result
- 已创建 `tasks/TASK01-*` 到 `tasks/TASK06-*` 的任务文件夹骨架。
- 已创建 `tests/unit`、`tests/integration`、`tests/e2e`、`tests/uat`、`tests/fixtures` 测试目录骨架。
- 已新增每个 TASK 的 `TASKxx-说明.md`。
- 已更新 `PROJECT-MANAGEMENT.md`，补充 TASK 文件夹管理规则和 integration 测试层。

### Reflection
- 本次未修改爬虫功能代码。下一步进入 TASK01 时，应从 `tests/unit` 的失败测试开始。

## 2026-05-27 11:39 - TASK01 Red 准备

### Observation
- TASK01 目标是把论坛列表页索引解析成稳定结构。
- 当前 `scripts/crawler_bbs.py` 只有 `crawl_articles()`，它把请求和解析混在一起，只返回 `title/url/href`。
- 全量爬取需要更完整字段：slug、url、title、author、author_id、reply_count、view_count、last_reply_time、post_time、source_page。
- 当前测试目录已建立，但还没有列表页 fixture 和失败测试。

### Plan
- 先保存一个列表页 HTML fixture，作为 TASK01 的离线测试样本。
- 编写 `tests/unit/test_index_parser.py`，先期待 `common.tgb_index.parse_bbs_list()` 存在并返回完整字段，使测试进入 Red。
- 再实现最小 `common/tgb_index.py`，让测试进入 Green。
- 最后把 `scripts/crawler_bbs.py` 的列表解析改为复用新 parser，保持旧返回字段兼容。

### Action
- 准备抓取列表页 fixture 并写失败测试。

### Result
- Red：`../../.venv/bin/python -m unittest tests.unit.test_index_parser` 首次因 `common.tgb_index` 不存在失败，符合预期。
- Green：新增 `common/tgb_index.py` 后，`tests.unit.test_index_parser` 通过。
- Refactor：`scripts/crawler_bbs.crawl_articles()` 已复用 `parse_bbs_list()`，并保持旧版 `title/url/href` 输出兼容。
- 真实 smoke test：`https://www.tgb.cn/bbs/1/1` 可返回约 70 条主列表帖子。
- 已更新 `tasks/TASK01-index-crawl/TASK01-说明.md`，标记 TASK01 MVP 完成。

### Reflection
- TASK01 已完成 MVP。本阶段未处理详情页、评论页、SQLite；下一步可进入 TASK02 或并行推进 TASK04 schema。

## 2026-05-27 11:43 - TASK02 Red 准备

### Observation
- 用户要求持续推进直到完成 TASK05。
- TASK02 目标是解析帖子详情页主帖结构化字段。
- 当前 `scripts/crawler_bbs.get_article_content()` 已能解析标题、主帖和楼主回复，但逻辑与请求混在一起，且没有独立测试。
- TASK02 应先建立详情页 fixture 和失败测试，再抽出 `common.tgb_article.parse_article_detail()`。

### Plan
- 保存一份可公开访问的帖子详情 HTML fixture。
- 编写 `tests/unit/test_article_parser.py`，期待 `parse_article_detail()` 返回 title、slug、author、author_id、view_count、comment_count、main_text、main_html、image_urls、comment_page_count。
- 运行测试进入 Red。
- 实现最小详情 parser，进入 Green。
- 暂不改动评论全量解析，评论留给 TASK03。

### Action
- 准备抓取详情页 fixture 并写 TASK02 失败测试。

### Result
- 待操作完成后回填。

### Reflection
- 本阶段只解析主帖详情，不负责全量评论和存储。

## 2026-05-27 11:47 - TASK02 完成与 TASK03 Red 准备

### Observation
- TASK02 的单元测试已通过，真实详情页 smoke test 也能返回标题、主帖、图片和楼主回复兼容输出。
- `scripts/crawler_bbs.get_article_content()` 已复用 `common.tgb_article.parse_article_detail()`。
- TASK03 目标是解析全量评论，而不再只筛楼主回复。

### Plan
- 基于 `article_detail_2s8aVDvYC5w.html` 编写评论解析失败测试。
- 期望 `common.tgb_comment.parse_comments()` 返回每条评论的 reply_id、user_id、username、is_author、floor、created_at、text、html、image_urls。
- 实现最小 parser 后，补一个分页 URL 构造函数测试。
- 暂不做网络全量分页调度，那属于 TASK05 的队列与状态层；TASK03 只提供 parser 和 URL 规则。

### Action
- 准备编写 TASK03 失败测试。

### Result
- Red：`common.tgb_comment` 不存在时，评论解析测试按预期失败。
- Green：新增 `common/tgb_comment.py` 后，`tests.unit.test_comment_parser` 通过。
- Refactor：`scripts/crawler_bbs.get_article_content()` 已复用 `parse_comments()`；旧报告路径仍只追加楼主回复，保持兼容。
- 全量单测：`tests.unit.test_index_parser tests.unit.test_article_parser tests.unit.test_comment_parser` 已通过。
- 已更新 `tasks/TASK03-comment-parse/TASK03-说明.md`，标记 TASK03 MVP 完成。

### Reflection
- 评论 HTML 的结构化 parser 已就位。TASK04 可进入 SQLite 存储层，让索引、主帖、评论三类记录先可幂等落库。

## 2026-05-27 12:03 - TASK04 Red 准备

### Observation
- TASK01/TASK02/TASK03 已分别产出 `BbsIndexRecord`、`ArticleDetail`、`CommentRecord`。
- 全量爬取需要一个统一 SQLite 存储层，先保证建表、upsert、去重、基础计数稳定。
- TASK05 的断点续爬会依赖 `crawl_queue` 和 `failures` 表，因此 TASK04 schema 应提前保留这两张表。

### Plan
- 编写 `tests/unit/test_storage.py`，先期待 `common.tgb_storage` 存在并提供建表与 upsert API。
- 使用临时 SQLite 数据库验证：建表、索引记录重复写入不重复、详情补充可覆盖、评论重复写入不重复。
- 实现 `common/tgb_storage.py`，使用 stdlib `sqlite3` 和 JSON 字符串保存图片列表。
- 更新 TASK04 文档和 ReAct 结果。

### Action
- 准备编写 TASK04 失败测试。

### Result
- Red：`tests.unit.test_storage` 首次因 `common.tgb_storage` 不存在失败，符合预期。
- Green：新增 `common/tgb_storage.py` 后，`tests.unit.test_storage` 4 个测试通过。
- 存储层已支持 SQLite 建表、索引记录 upsert、详情记录补充、评论记录按 `article_slug + reply_id` 去重。
- 已更新 `tasks/TASK04-storage/TASK04-说明.md`，标记 TASK04 MVP 完成。

### Reflection
- 存储契约已能承接 TASK01-TASK03 的结构化数据。TASK05 可以直接基于 `crawl_queue` 与 `failures` 实现断点续爬和失败重试。

## 2026-05-27 12:08 - TASK05 Red 准备

### Observation
- `common.tgb_storage.init_db()` 已创建 `crawl_queue` 和 `failures` 表。
- 断点续爬的关键不是马上抓全站，而是把 URL 任务状态做成可恢复、可重试、可查询的最小队列。
- 队列需要支持幂等入队、按优先级 claim、完成标记、失败退避、超过最大次数后转入 failed。

### Plan
- 编写 `tests/unit/test_resume_queue.py`，先期待 `common.tgb_resume` 提供队列 API。
- 覆盖：重复入队不重复、claim 后变 running、mark_done 后变 done、mark_failed 按次数重试并写 failures。
- 实现 `common/tgb_resume.py`，复用 TASK04 的 SQLite 表。
- 更新 TASK05 文档和 ReAct 结果。

### Action
- 准备编写 TASK05 失败测试。

### Result
- Red：`tests.unit.test_resume_queue` 首次因 `common.tgb_resume` 不存在失败，符合预期。
- Green：新增 `common/tgb_resume.py` 后，`tests.unit.test_resume_queue` 5 个测试通过。
- 队列状态机已支持幂等入队、按优先级 claim、完成标记、失败重试、退避时间、失败历史记录和 stale running 重置。
- 已更新 `tasks/TASK05-resume-and-retry/TASK05-说明.md`，标记 TASK05 MVP 完成。
- 已更新 `PROJECT-MANAGEMENT.md` 的当前进度和近期实施顺序。

### Reflection
- TASK01-TASK05 的最小闭环已经完成。下一步应进入 TASK06，把 parser/storage/queue 串成 sample/incremental/full 运行入口，并补 integration/e2e/UAT。

## 2026-05-27 12:14 - TASK01-TASK05 回归验证

### Observation
- TASK01-TASK05 都已有 MVP 实现和对应单元测试。
- 初次执行 `../../.venv/bin/python -m unittest discover tests` 时没有发现测试，因为测试目录缺少包初始化文件。

### Plan
- 补充 `tests/` 及各测试层目录的 `__init__.py`。
- 重新运行完整 unittest discover。
- 运行关键 Python 文件的 `py_compile`，确认语法层面无误。

### Action
- 新增 `tests/__init__.py`、`tests/unit/__init__.py`、`tests/integration/__init__.py`、`tests/e2e/__init__.py`、`tests/uat/__init__.py`。
- 执行 `../../.venv/bin/python -m unittest discover tests`。
- 执行 `../../.venv/bin/python -m py_compile common/tgb_index.py common/tgb_article.py common/tgb_comment.py common/tgb_storage.py common/tgb_resume.py scripts/crawler_bbs.py`。

### Result
- 完整测试发现已正常工作：15 个测试全部通过。
- 关键 Python 文件编译检查通过。

### Reflection
- TASK05 已完成。当前还没有进入 TASK06，因此 sample/incremental/full 的真实运行入口和 UAT 验收仍待下一阶段实现。

## 2026-05-27 12:20 - TASK06 阶段闸门补充

### Observation
- 用户确认下一步是否还不是全量跑，并追问这个思路是否体现在项目管理文档中。
- `PROJECT-MANAGEMENT.md` 已写明 TASK06 支持 `sample/incremental/full`，但阶段闸门不够醒目。

### Plan
- 在 TASK06 章节补充推进顺序和阶段闸门。
- 在运行模式章节补充 `单元稳定 -> sample -> incremental -> full` 的推荐执行顺序。
- 在近期实施顺序中明确 `sample` 通过前不进入 `full`。

### Action
- 更新 `PROJECT-MANAGEMENT.md`。

### Result
- 已补充 TASK06 阶段闸门：`sample` 未通过前不启动全量历史页抓取，`incremental` 未通过前不做长期运行。
- 已补充当前状态：处于 `sample 小闭环` 前置阶段。

### Reflection
- 后续进入 TASK06 时，应先写 `sample` 模式的 integration/e2e/UAT 测试，再实现运行入口。

## 2026-05-27 12:27 - TASK06 sample Red 准备

### Observation
- 用户要求推进完成 TASK06 的 sample 阶段。
- TASK01-TASK05 已有 parser、storage、resume queue，但还没有统一 sample runner。
- 现有 fixture 包含一页列表 HTML 和一页详情/评论 HTML，足够做离线 sample 小闭环测试。

### Plan
- 先写 e2e 测试：用 fixture fetcher 串起列表解析、详情解析、评论解析、SQLite 写入和队列状态。
- 再写 UAT 测试：验证 sample 输出 summary 具备用户验收所需字段和非全量运行标识。
- 运行测试进入 Red。
- 实现最小 `common.tgb_sample.run_sample()` 和 CLI `scripts/tgb_sample.py`。
- 更新 TASK06 文档、项目管理文档和日志结果。

### Action
- 准备新增 TASK06 sample 的 e2e/UAT 失败测试。

### Result
- Red：`tests.e2e.test_sample_runner` 与 `tests.uat.test_sample_acceptance` 首次因 `common.tgb_sample` 不存在失败，符合预期。
- Green：新增 `common/tgb_sample.py` 和 `scripts/tgb_sample.py` 后，sample e2e/UAT 通过。
- Refactor：补充 SQLite 连接关闭，避免测试中的资源 warning。
- 新增 `Makefile`，提供 `make test`、`make test-unit`、`make test-e2e`、`make test-uat`、`make crawl-sample`。
- 更新 `tasks/TASK06-full-run/TASK06-说明.md`，标记 sample 阶段完成，incremental/full 未开始。
- 更新 `PROJECT-MANAGEMENT.md` 与 `README.md`，明确 sample 已完成，下一步才是 incremental。
- 完整测试：`make test` 通过，17 个测试全部通过。
- 编译检查：`common/tgb_sample.py`、`scripts/tgb_sample.py` 等关键文件通过 `py_compile`。
- 真实 sample 命令已验证：`scripts/tgb_sample.py --list-pages 1 --max-articles 3 --comment-pages 1 --interval 0.1` 成功生成 `data/tgb-sample.sqlite`，抓取 1 页列表、3 篇详情、3 个评论页，无 failures。当前实时样本的这 3 篇评论数为 0；评论写入链路已由 fixture e2e/UAT 覆盖。

### Reflection
- TASK06 sample 阶段已完成。下一阶段应先设计 incremental 的新增判定和停止条件，仍不进入 full 全量抓取。

## 2026-05-27 12:43 - TASK06 sample 有评论帖子补验收

### Observation
- 用户认可 sample 阶段基本通过，但指出真实 sample 没有抓到有评论的帖子。
- 当前 live sample 的 `comments` 表为 0，评论链路仅由 fixture e2e/UAT 覆盖。
- 需要按发帖时间排序，抓当前列表页最早的 5 个帖子，观察真实评论入库情况。

### Plan
- 使用当前登录 Cookie 请求 `https://www.tgb.cn/bbs/1/1`。
- 用 `parse_bbs_list()` 解析列表，按 `post_time` 升序选择最早 5 个帖子。
- 写入单独验证库 `data/tgb-sample-earliest.sqlite`，避免污染原 sample 库。
- 抓取 5 篇详情和评论第一页，统计 `articles`、`comments`、`failures`。

### Action
- 准备执行 live 补验收脚本。

### Result
- 按当前列表页 `post_time` 升序抓最早 5 篇，生成 `data/tgb-sample-earliest.sqlite`。
- 这 5 篇列表 `reply_count` 均为 0，因此真实评论入库仍为 0；详情抓取和正文入库正常，无 failures。
- 随后在同一列表页筛选 `reply_count > 0` 的帖子，再按 `post_time` 升序抓取，生成 `data/tgb-sample-comments.sqlite`。
- 当前页只有 2 篇 `reply_count > 0` 的候选，已全部抓取；`comments` 表成功写入 4 条评论，无 failures。
- 已抽查评论字段：reply_id、username、is_author、floor_label、created_at、text 均能入库。

### Reflection
- live 评论入库已补验收通过。后续 incremental 阶段应把“按 reply_count 目标抽样”作为 UAT 用例之一，避免随机 sample 抽不到评论。

## 2026-05-27 12:58 - TASK06 incremental 设计落档

### Observation
- 用户确认进入 incremental 设计阶段，并询问是否需要新建项目管理文档以及拆成几个 TASK。
- 当前 `PROJECT-MANAGEMENT.md` 已是总控文档，不宜另起一套总项目管理文档。
- TASK06 已承载 sample/incremental/full 三种运行模式，适合在 TASK06 内新增细分设计文档。

### Plan
- 继续使用 `PROJECT-MANAGEMENT.md` 作为总控文档。
- 在 `tasks/TASK06-full-run/` 下新增 `incremental-design.md`。
- 将 incremental 拆成 5 个子任务：TASK06A 总页数与分页边界、TASK06B 新帖发现、TASK06C 停止条件、TASK06D 近期评论复查、TASK06E 命令与验收。
- 更新 TASK06 说明文档和总控文档。

### Action
- 准备写入 incremental 设计文档和文档索引。

### Result
- 已新增 `tasks/TASK06-full-run/incremental-design.md`。
- 已将 incremental 拆成 5 个子任务：TASK06A 总页数与分页边界、TASK06B 新帖发现、TASK06C 停止条件、TASK06D 近期评论复查、TASK06E 命令与验收。
- 已更新 `tasks/TASK06-full-run/TASK06-说明.md`，将 incremental 标记为设计中。
- 已更新 `PROJECT-MANAGEMENT.md`，把 TASK06 状态更新为 sample 完成、incremental 设计中，并写入 TASK06A-TASK06E。

### Reflection
- incremental 设计已落档。下一步若继续实现，应从 TASK06A 的 Red 测试开始。

## 2026-05-27 13:07 - TASK06A-E Red 准备

### Observation
- 用户要求持续推进直到 TASK06E 完成。
- 列表页 fixture 中存在 `gotoPage(92715,1,92715)` 和跳转页码上限，可用于解析总页数。
- 当前已有 sample runner，但还没有 incremental pagination、stop policy、增量 runner、评论复查和命令入口。

### Plan
- TASK06A：为分页解析写单测，期待 `parse_bbs_pagination()` 和 `build_bbs_page_url()`。
- TASK06B/C/D：为 incremental runner、停止条件、评论复查写单元/e2e 测试。
- TASK06E：为 UAT 摘要和 Makefile/CLI 入口写验收测试。
- 先让测试 Red，再实现最小代码让测试 Green，最后回归和文档回填。

### Action
- 准备新增 TASK06A-E 的测试。

### Result
- Red：新增分页、incremental policy、incremental e2e、incremental UAT 测试后，因 `build_bbs_page_url`、`parse_bbs_pagination` 和 `common.tgb_incremental` 不存在而失败，符合预期。
- Green：新增 `common.tgb_index` 分页函数、`common/tgb_incremental.py`、`scripts/tgb_incremental.py` 和 `make crawl-incremental` 后，新增 9 个 TASK06A-E 测试通过。
- TASK06A：完成列表总页数与分页边界解析。
- TASK06B：完成增量新帖发现与详情入队。
- TASK06C：完成停止条件策略。
- TASK06D：完成近期评论复查候选选择与 runner 复查步骤。
- TASK06E：完成 incremental 命令入口、Makefile target 和 UAT 摘要。
- 已更新 `PROJECT-MANAGEMENT.md`、`tasks/TASK06-full-run/TASK06-说明.md`、`tasks/TASK06-full-run/incremental-design.md` 和 `README.md`。

### Reflection
- incremental MVP 已完成；下一阶段才考虑 full/backfill 倒序历史回填。

## 2026-05-27 13:20 - 最老页最老 5 条 sample 验证

### Observation
- 用户希望抓当前最老页的最老 5 条帖子作为 sample 查看。
- incremental 已能解析 `total_pages`，因此可以自动定位 `/bbs/{total_pages}/1`。
- 这仍是 sample 验证，不启动 full 全量抓取。

### Plan
- 请求 `/bbs/1/1`，解析当前 `total_pages`。
- 请求 `/bbs/{total_pages}/1`，解析最后一页列表。
- 选取最后一页最后 5 条帖子。
- 抓取这 5 篇详情和评论第一页，写入 `data/tgb-sample-oldest.sqlite`。
- 汇总正文长度、评论数、失败数和链接。

### Action
- 准备执行 live 最老页 sample 脚本。

### Result
- 当前解析到 `total_pages = 92760`，最后页 URL 为 `https://www.tgb.cn/bbs/92760/1`。
- 最后一页可解析 8 条列表记录。
- 已取最后 5 条帖子抓取详情与评论第一页，写入 `data/tgb-sample-oldest.sqlite`。
- 本次 `articles_total = 8`，`comments_total = 84`，`failures = 0`。
- 5 篇详情均抓到正文，正文长度分别为 473、1597、629、141、335。
- 5 篇评论分别入库 5、7、14、9、49 条。最后一篇列表回复数为 137，但仅抓第一页评论，后续 full/backfill 需要补评论分页。

### Reflection
- 老页面详情和评论结构与当前 parser 基本兼容。评论分页是 full/backfill 的关键风险点：只抓第一页会漏掉多页评论。

## 2026-05-27 13:32 - TASK07A-E full/backfill Red 准备

### Observation
- 用户要求推进到 TASK07E 完成。
- sample 与 incremental MVP 已完成，但 full/backfill 尚未设计和实现。
- 老页 sample 暴露关键风险：多页评论未补全，例如回复数 137 但第一页只入库 49 条。

### Plan
- TASK07A：新增 full/backfill 设计文档和任务说明。
- TASK07B：实现评论分页规划与抓取补全，先写单元/e2e 测试。
- TASK07C：实现倒序列表页规划，从 `total_pages` 往前抓。
- TASK07D：提供 backfill sample runner 和命令入口。
- TASK07E：补 UAT 摘要和运行闸门，确保仍不是长期 full 全量运行。

### Action
- 准备新增 TASK07 测试和文档骨架。

### Result
- Red：新增 `tests.unit.test_backfill_policy`、`tests.e2e.test_backfill_runner`、`tests.uat.test_backfill_acceptance` 后，因 `common.tgb_backfill` 不存在失败，符合预期。
- Green：新增 `common/tgb_backfill.py`、`scripts/tgb_backfill_sample.py` 和 `make crawl-backfill-sample` 后，backfill 5 个测试通过。
- TASK07A：完成 `tasks/TASK07-backfill-full/backfill-design.md` 和 `TASK07-说明.md`。
- TASK07B：完成评论分页规划与抓取，sample 可抓第 1、2 页评论。
- TASK07C：完成从 `total_pages` 倒序规划列表页。
- TASK07D：完成 backfill sample 命令入口。
- TASK07E：完成 UAT 摘要和 `manual_approval_required` full 运行闸门。
- 完整回归：`make test` 通过，29 个测试全部通过。
- 编译检查：关键 `common/` 与 `scripts/` 文件均通过 `py_compile`。
- live backfill smoke：`scripts/tgb_backfill_sample.py --max-list-pages 1 --max-articles-per-page 1 --max-comment-pages 2` 成功；解析 `total_pages = 92762`，倒序抓 1 个最后页、1 篇详情、2 个评论页，入库评论 92 条，`failures = 0`，`full_run = false`。

### Reflection
- TASK07E 已完成，但长期 full 全量仍未启动。下一步需要人工审核 backfill sample 输出后，再决定是否设计长期 full 参数。

## 2026-05-27 13:48 - TASK08/09 Red 准备

### Observation
- 用户要求把 TASK08/09/10 全流程写入项目管理文件，并持续推进完 TASK08 和 TASK09。
- 当前已有 backfill sample，但还没有长期 full 参数定稿、队列化 full trial、中断恢复演练和试运行报告。
- TASK10 才是完整版长期 full，本阶段不能越过人工闸门。

### Plan
- 更新项目管理文件，补 TASK08、TASK09、TASK10 路线。
- TASK08：新增 full 参数、校验、队列规划、运行前闸门的测试与实现。
- TASK09：新增受控 full trial runner、CLI、Makefile target、UAT 摘要。
- 执行完整回归和轻量 live smoke。

### Action
- 准备新增 TASK08/09 测试。

### Result
- Red：新增 `tests.unit.test_full_policy`、`tests.e2e.test_full_trial_runner`、`tests.uat.test_full_trial_acceptance` 后，因 `common.tgb_full` 不存在失败，符合预期。
- Green：新增 `common/tgb_full.py`、`scripts/tgb_full_trial.py` 和 `make crawl-full-trial` 后，TASK08/09 6 个测试通过。
- TASK08：完成 full 参数模型、校验、队列规划、运行报告与人工闸门。
- TASK09：完成受控 full trial runner、CLI、Makefile target、e2e/UAT。
- 已更新 `PROJECT-MANAGEMENT.md`、`README.md`、`tasks/TASK08-full-preflight/`、`tasks/TASK09-full-trial/`、`tasks/TASK10-full-production/`。
- 完整回归：`make test` 通过，35 个测试全部通过。
- 编译检查：关键 `common/` 与 `scripts/` 文件均通过 `py_compile`。
- live full trial smoke：`scripts/tgb_full_trial.py --max-list-pages 1 --max-articles-per-page 1 --max-comment-pages 2` 成功；解析 `total_pages = 92763`，倒序入队 1 个列表页、1 篇详情、2 个评论页，`queue_done = 4`，`failures = 0`，`full_run = false`，`full_run_gate = manual_approval_required`。

### Reflection
- TASK08/09 已完成；TASK10 才是长期 full production，仍需用户手动确认。

## 2026-05-27 14:02 - TASK10 第一批人工确认启动

### Observation
- 用户明确确认启动 TASK10，并要求先按保守参数跑第一批。
- TASK09 full trial 已通过，具备 list_page、article、comment_page 三类队列和人工闸门。
- 当前还没有单独的 TASK10 production batch 命令，需要避免误用 `full_trial` 摘要。

### Plan
- 增加 TASK10 production batch 入口，要求显式传入 `--manual-approval`。
- 第一批采用保守参数：倒序最后 1 页、每页最多 70 篇、每篇最多 3 页评论、间隔 1 秒。
- 输出 `mode=full_batch`、`full_run=true`、`manual_approval=true`。
- 跑完后汇总列表页、详情、评论页、失败数。

### Action
- 准备新增 production batch CLI 并启动第一批。

### Result
- 待操作完成后回填。

### Reflection
- 第一批是受控 production batch，不是无限期后台全站运行。

## 2026-05-27 14:18 - TASK11 反爬检测与熔断 Red 准备

### Observation
- TASK10 第一批出现异常：帖子详情请求返回 200，但 HTML 是“错误页面_淘股吧”，导致空详情被错误标记为 done。
- 用户浏览器也无法访问帖子，疑似触发站点风控/临时限制。
- 当前必须暂停 live 抓取，先补反爬检测、错误页熔断和保守限速策略。

### Plan
- 新增 TASK11 文档，明确保护目标和禁止继续请求的条件。
- 写 Red 测试：错误页应被识别为 blocked；full batch 遇到 blocked 应停止，不入库详情、不标记 done。
- 实现 `common.tgb_guard`，提供页面分类、反爬异常、保守限速配置。
- 修改 full runner，在列表/详情/评论页 fetch 后立即校验页面。
- 更新项目管理文档和 README。

### Action
- 准备新增 TASK11 测试与文档骨架。

### Result
- Red：新增 `tests.unit.test_guard` 和 `tests.e2e.test_full_guard` 后，因 `common.tgb_guard` 不存在、full runner 不熔断而失败，符合预期。
- Green：新增 `common/tgb_guard.py` 并在 `common/tgb_full.py` 接入 `require_normal_page()` 后，guard 相关 9 个测试通过。
- 修正误判：列表 fixture 中包含“验证码”文本片段，已避免把正常列表页误判为 blocked。
- 已新增 `tasks/TASK11-anti-bot-guard/TASK11-说明.md`。
- 已更新 `PROJECT-MANAGEMENT.md` 和 `README.md`。

### Reflection
- TASK11 MVP 已完成。当前不继续 live 抓取，等待站点访问恢复后再用保守参数重启小批次。

## 2026-05-28 09:00 - TASK10 恢复后保守 smoke

### Observation
- 用户反馈浏览器已可正常访问帖子。
- 需要先确认站点访问恢复，再用 TASK11 保守参数小批量恢复。

### Plan
- 先请求一篇已知老帖做健康探针，使用 guard 判断是否正常页面。
- 若正常，运行单独数据库 `data/tgb-full-recovery-smoke.sqlite`，参数为最后 1 页、最多 3 篇、每篇 1 页评论、10 秒间隔。
- 汇总空详情、评论、失败和数据库大小。

### Action
- 已执行健康探针：`https://www.tgb.cn/a/1yktHE16WgM`。
- 已执行保守 smoke：`scripts/tgb_full_batch.py --manual-approval --db data/tgb-full-recovery-smoke.sqlite --max-list-pages 1 --max-articles-per-page 3 --max-comment-pages 1 --interval 10.0`。

### Result
- 健康探针正常：guard 为 `NORMAL`，标题为“世界因你而精彩”，正文长度 335，评论总数 137，第一页评论 49。
- 保守 smoke 成功：`full_run=true`、`manual_approval_granted`、`list_pages_done=1`、`article_details_fetched=3`、`comment_pages_fetched=3`、`comments_seen=72`、`failures=0`。
- 数据库 `data/tgb-full-recovery-smoke.sqlite`：3 篇详情、72 条评论、0 条失败、0 个空详情，大小 128K。

### Reflection
- 访问已恢复，TASK11 熔断未触发。正式恢复前建议先清理/隔离此前 `data/tgb-full.sqlite` 中被错误页污染的空详情，再继续保守批次。

## 2026-05-28 09:18 - TASK13 批次台账与保守 full 重跑

### Observation
- 用户确认删除 `data/tgb-full.sqlite`，直接从干净库重跑。
- TASK11 熔断已完成，恢复 smoke 已验证可访问。
- 当前应使用保守参数，避免再次触发风控。

### Plan
- 删除旧 `data/tgb-full.sqlite` 及 WAL/SHM 文件。
- 创建 TASK13 批次台账目录。
- 使用保守参数运行第一批：最后 1 页、最多 3 篇、每篇 1 页评论、10 秒间隔。
- 跑完后统计 articles、comments、article_pages、failures、空详情、数据库大小，并写入台账。

### Action
- 已删除旧 `data/tgb-full.sqlite`。
- 准备启动保守 full batch。

### Result
- TASK13 Batch 001 完成。
- 运行参数：`--max-list-pages 1 --max-articles-per-page 3 --max-comment-pages 1 --interval 10.0`。
- 输出：`data/tgb-full.sqlite`。
- 批次结果：`total_pages=92772`，`planned_pages=[92772]`，`list_pages_done=1`，`index_records_seen=32`，`article_details_fetched=3`，`comment_pages_fetched=3`，`comments_seen=72`，`failures=0`。
- 数据库复核：`articles=32`，`comments=72`，`article_pages=3`，`queue_done=7`，`empty_detail_articles=0`，数据库大小 `128K`。
- 已新增 `tasks/TASK13-batch-ledger/TASK13-说明.md` 和 `tasks/TASK13-batch-ledger/outputs/batch-ledger.md`。

### Reflection
- Batch 001 通过。下一批可继续保持同参数，连续 3-5 批稳定后再考虑把 `max_articles_per_page` 从 3 提高到 5。

## 2026-05-28 09:32 - TASK13 Batch 002-005 连续保守批次

### Observation
- 用户确认继续执行稳态保守批次。
- Batch 001 已通过，当前参数稳定：每批 1 页、3 篇、1 页评论、10 秒间隔。

### Plan
- 继续同参数执行 Batch 002-005。
- 页码从上一批 92772 继续倒序：92771、92770、92769、92768。
- 每批使用同一个 `data/tgb-full.sqlite`，累积入库。
- 跑完后检查 failures、empty_detail_articles、comments、数据库大小，并更新台账。

### Action
- 准备启动连续批次。

### Result
- Batch 002-005 已完成，参数保持：每批 1 页、最多 3 篇、每篇 1 页评论、10 秒间隔。
- Batch 002：page 92771，列表 70 条，详情 3 篇，评论页 3 页，评论 13 条，失败 0。
- Batch 003：page 92770，列表 70 条，详情 3 篇，评论页 3 页，评论 29 条，失败 0。
- Batch 004：page 92769，列表 70 条，详情 3 篇，评论页 3 页，评论 12 条，失败 0。
- Batch 005：page 92768，列表 70 条，详情 3 篇，评论页 3 页，评论 1 条，失败 0。
- 当前累计数据库复核：`articles=312`，`detail_count=15`，`comments=127`，`article_pages=15`，`failures=0`，`queue_done=35`，`empty_detail_articles=0`，数据库大小 `576K`。
- 已更新 `tasks/TASK13-batch-ledger/outputs/batch-ledger.md`。

### Reflection
- 连续 5 个保守批次稳定通过。下一步可以继续同参数再跑几批，或小幅把 `max_articles_per_page` 从 3 提高到 5，但不建议同时提高评论页和列表页数量。

## 2026-05-28 09:50 - TASK13 Batch 006 小幅放大

### Observation
- 用户选择小幅放大方案。
- Batch 001-005 均稳定，`failures=0`、`empty_detail_articles=0`。

### Plan
- 只把 `max_articles_per_page` 从 3 提高到 5。
- 其他参数保持：每批 1 页、每篇 1 页评论、10 秒间隔。
- 先跑 Batch 006，页码 92767。
- 跑完复核 failures、empty_detail_articles、comments、数据库大小。

### Action
- 准备启动 Batch 006。

### Result
- Batch 006 完成，页码 92767。
- 参数：每批 1 页、最多 5 篇、每篇 1 页评论、10 秒间隔。
- 批次结果：列表 70 条，详情 5 篇，评论页 5 页，评论 8 条，失败 0。
- 数据库复核：`articles=382`，`detail_count=20`，`comments=135`，`article_pages=20`，`queue_done=46`，`failures=0`，`empty_detail_articles=0`，数据库大小 `640K`。
- 已更新 `tasks/TASK13-batch-ledger/outputs/batch-ledger.md`。

### Reflection
- Batch 006 稳定通过。建议继续用同样放大参数跑 2-3 批，再考虑是否提高评论页数量。

## 2026-07-17 - 指定用户 moreTopic 主帖全集抓取

### Observation
- 用户需要抓取 `https://www.tgb.cn/user/blog/moreTopic?userID=252069`，用于长期阅读 `柏拉爱空` 的题材复盘。
- 现有 `parse_bbs_list()` 能解析 `moreTopic` 页面中的主帖记录，但缺少指定用户分页调度入口。
- 实测页面脚本包含 `pageNum = 37`，可自动识别全集页数。

### Plan
- 新增 `common/tgb_user_topics.py`：负责构造用户主帖分页 URL、解析分页、规划页码、入库索引、可选抓详情/评论。
- 新增 `scripts/tgb_user_topics.py`：提供 CLI。
- 新增 unit/e2e 测试保护分页规则和小闭环入库。
- 更新 `README.md`、`SKILL.md`、`Makefile`。

### Action
- 新增命令：
  - `python scripts/tgb_user_topics.py --user-id 252069 --all`
  - `python scripts/tgb_user_topics.py --user-id 252069 --max-pages 2 --fetch-details --max-articles 5 --comment-pages 1`
  - `make crawl-user-topics USER_ID=252069`
- 修正 `Makefile` 默认 `PYTHON` 路径为 SMK 根目录 `.venv`。
- 详情抓取队列改为：页码越新、列表位置越靠前，优先级越高。

### Result
- 已真实抓取 `柏拉爱空 userID=252069` 全量主帖索引到 `data/tgb-user-252069.sqlite`。
- 全集索引结果：`total_pages=37`，`index_records_saved=3618`，`failures=0`。
- 轻量详情验证：已抓取 3 篇详情、14 条评论，`failures=0`。
- 最新优先级验证：最新详情从 `7月16日 猴市` 开始抓取。
- 测试：
  - `python -m unittest tests.unit.test_user_topics tests.e2e.test_user_topics_runner` 通过。
  - `python -m unittest discover -s tests/unit -p 'test_*.py'` 通过，33 tests。
  - `python -m unittest discover -s tests/e2e -p 'test_*.py'` 通过，6 tests。

### Reflection
- 当前建议先用 `--all` 建全集索引，再用 `--fetch-details --max-articles N` 小批量补正文和评论。
- 该数据源适合接入 SMK 题材研究：作为“短线老师复盘/题材命名/情绪体感”的人工高质量文本层。

## 2026-07-17 - 指定用户 moreTopic 正文详情全量补库

### Observation
- 用户指出：只抓完 `moreTopic` 列表索引还不够，后续研究需要把帖子正文也全部拉下来入库。
- 前一阶段 `data/tgb-user-252069.sqlite` 已有 `3618` 条主帖索引，但正文详情只做了小批量验证，并非全量详情库。
- 需要区分两个口径：`articles` 是列表索引，`details` 才是正文详情是否已抓取。

### Plan
- 新增 `--details-only` 模式：不重扫列表页，直接从已有 SQLite 中找 `fetched_at = ''` 的帖子续抓正文详情和首屏评论。
- 批量补齐 `柏拉爱空 userID=252069` 的全部主帖正文。
- 补库完成后复核 `articles/details/missing_details/comments/failures`，并跑 unit/e2e 回归。

### Action
- 增加 `enqueue_missing_article_details()`，只为缺失详情且队列中不存在待抓任务的帖子入队，避免每次 details-only 重新扫描大量 pending。
- 新增命令示例：
  - `python scripts/tgb_user_topics.py --user-id 252069 --details-only --max-articles 200 --comment-pages 1`
  - `make crawl-user-topic-details USER_ID=252069 MAX_ARTICLES=200`
- 分批执行 details-only，保持请求间隔，补齐剩余正文。

### Result
- `data/tgb-user-252069.sqlite` 最终复核：
  - `articles=3618`
  - `details=3618`
  - `missing_details=0`
  - `comments=6524`
  - `pending_articles=0`
  - `running_articles=0`
  - `done_articles=3618`
  - `failures=0`
- 最后一批输出：`article_details_fetched=903`，`comment_pages_fetched=903`，`queue_done=3618`，`failures=0`。
- 回归测试：
  - `python -m unittest tests.unit.test_user_topics tests.e2e.test_user_topics_runner`：6 tests OK。
  - `python -m unittest discover tests/unit`：34 tests OK。
  - `python -m unittest discover tests/e2e`：7 tests OK。

### Reflection
- 以后说“指定用户帖子全集入库”，必须同时检查 `articles == details` 且 `missing_details = 0`；只完成 `articles` 只能称为“列表索引全集”。
- 对于这类长期复盘老师数据，推荐流程是：先 `--all` 建索引，再用 `--details-only` 分批补正文，必要时再追加更多评论分页。
