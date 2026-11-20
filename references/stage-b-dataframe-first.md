---
type: reference
status: structural-green
owner: taoguba-crawler
migration: source-case-full-projection-green / cross-author-forward-test-pending
---

# Stage B DataFrame-first 全量推断合同

## 何时使用

小型pilot或少量连续窗口可以直接逐窗建立十类机会矩阵。进入全量阶段时，若同时出现以下特征，默认先采用DataFrame-first，而不是把每个时间窗的所有计算重复交给模型：

- Stage A已经形成稳定、全量、可审计的结构化ledger；
- 仓位行或时间窗数量较多；
- 大部分候选来自相同的确定性公式、相邻关系或字段完整性检查；
- 真正需要语义判断的只是身份链、重新开仓、开仓均价前提、竞争候选和异常口径等少数项目。

DataFrame-first是执行形态，不改变[两阶段合同](position-screenshot-two-stage-contract.md)或[十类机会目录](position-inference-opportunities.md)。如果Stage A schema尚不稳定、来源SHA漂移或多数判断仍需回图，先修Stage A，不为追求批量化强建表。

## 标准流水线

```text
Stage A latest ledger + coverage/hash audit
→ snapshots_df + positions_df
→ safe account/time links
→ deterministic candidates + ten-kind opportunity_matrix
→ exact stock-code resolution + explicit unresolved names
→ high-risk semantic review queue
→ conservative clusters + isolated worker outputs
→ main-agent merge / calibration / market-data request queue
→ positions_enriched wide table
→ position_claims_long audit table
→ completeness audit + queue-zero proof + Human Gate
```

每一步都必须记录输入SHA、输出SHA、行数守恒和运行ID。任何中间表都是可重建read model，不成为新的事实owner。

如下游需要交易episode、交易频率、可见资产曲线、胜率或赔率，由`miy-smk-broker-account-record-analysis`消费这些read model。Stage B不在宽表中内嵌跨来源事件定义或统计分母。

下游交接至少保留：安全账户键、时间、明示正仓/0仓字段、直接可见/机器候选/竞争/未决身份、数量/市值/盈亏代理、claim状态、source locator和SHA。

## 三张核心表

### `positions_enriched`

一条Stage A仓位行对应一行。必须原样保留Stage A全部仓位与快照字段，包括`raw_text / normalized_value / visibility / mask_id / unit / stable locator / source SHA`，再追加：

- 来源可见证券代码与解析状态；
- 十类候选的完整JSON与数量；
- 有效身份候选、失效身份候选和竞争状态；
- worker/主审覆盖、行情问题数和身份完成状态；
- 未决claim kinds与来源/证据回链。

多个有效候选不得压成一个“最佳答案”。宽表用于筛选和学习，不覆盖Stage A单元格。

### `position_claims_long`

一条候选×一个对象仓位一行。至少保存：

- `claim_kind / candidate / estimate / range / unit / method`；
- 公式输入、假设、问题码和basis SHA；
- subject稳定ID、Stage A存在性与代码解析状态；
- worker决策/置信度、主审决策/置信度与校准依据；
- 外部行情case、回执SHA、复权/单位和问题状态；
- `candidate_review_relation`与`human_confirmed`。

输入候选关系至少区分：

```text
input-candidate-supported
input-candidate-not-supported
input-candidate-superseded-by-new-proposal
input-candidate-unresolved
new-agent-proposal
market-confirmatory-receipt
```

被否定或替代的候选继续留在长表，但不能进入宽表的有效候选集合。

### `snapshot_opportunity_matrix`

每个合格快照/时间窗逐项保存十类机会的`candidate / unresolved / hard-rejected / not-applicable`处置。它是“是否漏审”的owner；长表有多少成功claim不能替代机会矩阵完整性。

## 确定性层与语义层

优先在DataFrame确定性层完成：

- Stage A行/字段守恒与可见性分账；
- 安全账户键和明确时间排序；
- 已满足前提的Decimal公式及区间传播；
- 同一公开身份的数量变化；
- 精确六位代码、本地精确别名和人工维护的历史名称映射；
- `requires_model_review / requires_market_data`标记；
- 十类机会矩阵中可机械确定的`candidate / unresolved / not-applicable`。

只把高风险语义项送入模型/主审：

- MASK与后续公开身份是否唯一闭合；
- 开仓均价、重新开仓或清仓的业务前提是否成立；
- 多匿名行、多公开行、行序变化和竞争候选；
- 时间、账户、裁切或字段语义存在冲突；
- 公式与券商口径/K线表面不相容，需要判断补证方向。

确定性公式候选可以保持`unreviewed`；“高风险语义queue为0”不等于每条机械候选已人工确认。

## 保守聚类与agent分工

- 只在相同安全账户键、时间有序且间隔上限明确时聚类；`ACCOUNT-* / MULTI-* / 未显示账户`不得跨快照猜成同账户。
- singleton必须物理隔离；不能为了减少任务数把无账户端点的记录拼成链。
- worker只读取Stage A表、机会矩阵、候选与必要的代码解析，不重复逐图执行Stage A。
- 原图回看只由主审在Stage A争议、locator/裁切/可见性冲突、source SHA漂移或Human Gate要求时触发。
- worker输出先做schema、input SHA、matrix守恒和引用隔离验证，再由主审决定支持、否定、替代、部分解决、保持未决或升级Stage A争议。
- 多agent只写隔离目录；合并账本、正式read model与Human Gate由唯一主控维护。

## 外部行情队列

DataFrame不得直接绕过owner批量抓行情。它只生成带候选证券、日期、用途和所需口径的`requires_market_data`队列，再由`miy-stock-data`路由到`kline / pywencai`等owner。每次回填保持独立receipt；`pass / limited / problem`只说明相容性，不自动确认或硬拒绝身份。

当价格表面冲突时，继续遵守raw/qfq/hfq、公司行为、券商成本和已实现盈亏口径门；未闭合时保留问题值和issue code。

## 全量Green

全量机器候选层至少满足：

- Stage A快照与仓位行一对一守恒，全部来源列保留；
- 十类机会矩阵覆盖全部合格窗口；
- 高风险语义队列有冻结分母，合并账本无重复/漏项，复算remaining为0；
- candidate、未决、硬拒绝、不适用、否定、替代和竞争候选分别可查询；
- 所有claim subject都能回链Stage A，未知subject为0；
- 证券名解析只使用精确/显式映射，未命中名称单独导出，不模糊猜名；
- 未决MASK、竞争候选、失效旧候选、未编码候选和行情问题都有独立导出；
- 机器产物中的`human_confirmed`为0，人工状态只由Human Gate追加；
- 宽表列字典、构建审计、完整性审计、输入/输出SHA和回归测试Green。

Stage B Green不是MASK答案率100%。缺乏安全端点的记录应稳定留在未决表；强填会使项目变Red。

## 实现迁移状态

来源案例已经证明DataFrame-first能完成大规模source-case全量投影、语义队列归零和宽/长表守恒。当前构建脚本仍绑定来源TASK的Stage A SQLite schema、运行目录和审计字段，暂不原样复制到provider；它们是`source-case implementation`，不是通用资产。

在第二作者/第二版式forward-test前，先按本合同在新TASK重建最小适配层并冻结Green。若两个案例共享稳定输入schema，再将构建器抽成provider脚本；此前迁移状态保持`structural-green / source-case-full-projection-green / cross-author-forward-test-pending`。
