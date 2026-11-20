---
name: tgb-position-history-inference
description: 从已经全量人工核对的淘股吧券商截图记录中，按账户与时间生成可回链且机会完整的持仓历史推断。用于打码股票后续揭名、市值、数量、隐含价格、持仓平均成本、当日盈亏参考价、加权开仓均价、加减仓、清仓和重新开仓；大规模全量任务采用DataFrame-first分离确定性投影与高风险语义复核，并可经miy-stock-data调用K线等辅助证据。不得在Stage A未Green时运行，也不把机器候选写成人工确认。
---

# TGB持仓历史推断

## 前置门

开始前必须读取：

- [`../../references/position-screenshot-two-stage-contract.md`](../../references/position-screenshot-two-stage-contract.md)；
- [`../../references/position-inference-opportunities.md`](../../references/position-inference-opportunities.md)；
- 全量或大规模任务另读[`../../references/stage-b-dataframe-first.md`](../../references/stage-b-dataframe-first.md)；
- 输入任务的Stage A字段合同、覆盖审计和人工Gate决定。

只有`Stage A Green + source SHA未漂移`时才执行。OCR草稿、旧窄字段台账、部分人工抽样或一个已确认source pair均不能解锁全量推断。

## 执行模式

- `pilot`：冻结一段连续、同账户且信息密度足够的时间窗口，生成候选、未决和Human Gate。
- `full-inference`：pilot Gate通过后，处理全部合格MASK和账户时间序列。Stage A已有稳定结构表且规模较大时，默认先评估DataFrame-first；小样本仍可直接逐窗审阅。

## 流程

1. 按`author_id + broker + masked account key`分组，并按真实截图时间排序；时间未知记录保留但不强行串联。
2. 为每个合格仓位时间窗建立完整`opportunity_matrix`，逐项处置`identity / market-value / implied-price / quantity / holding-average-cost / daily-pnl-reference-price / opening-average-price / position-change / closure / reopening`；不能先套公式再假定前提成立，也不能静默省略没有成功算出的类型。
3. 全量DataFrame-first路线先生成`snapshots / positions / safe links / deterministic candidates / opportunity matrix`，证明Stage A行与字段守恒；只把身份链、开仓/重新开仓前提、竞争候选和口径异常等高风险项送入语义队列。不得把全部公式计算重复交给模型，也不得把“语义queue为0”写成“所有机械候选已人工确认”。
4. 常规推断只消费已达到Green的Stage A人工转录表；账户汇总、逐仓字段、稳定token和后续公开名称均从该表读取。原图只在Stage A字段自相矛盾、locator/裁切/可见性有争议、source SHA漂移或Human Gate明确要求时，由主审选择性回看；subagent不得重复执行Stage A逐图阅读。
5. 语义队列按安全账户键和有序时间保守聚类；无可靠账户端点的singleton物理隔离。worker写隔离目录并先通过schema、input SHA、matrix守恒与引用边界校验；主审唯一维护支持、否定、替代、未决、部分解决和Stage A升级裁决。
6. 需要行情、候选集合或交易日时，完整读取`miy-stock-data`并由它路由实际owner；DataFrame只生成`requires_market_data`请求队列，单票历史日线通常进入`kline`。
7. 保存外部证据回执：owner、capability、请求/实际日期、来源、SHA、复权、单位、fallback、失败和未授权下游。
8. 用行情排异前先统一价格口径：明确raw/qfq/hfq、除权除息或送转配股、券商历史成本调整及当日已实现盈亏。未完成口径闭合时，超出未复权日K只能记为`unresolved / adjustment-or-broker-basis-dispute`，不能直接`hard-rejected`。
9. 分别形成identity、quantity、market-value、implied-price、holding-average-cost、daily-pnl-reference-price、opening-average-price、position-change、closure或reopening claim；每项保留公式、输入、假设、区间、反证、执行者置信度、主审置信度和basis SHA。详细公式只从推断机会目录读取；机械算术可调用`../../scripts/tgb_position_inference_math.py`。
10. 全量路线最终交付一仓一行的`positions_enriched`宽表、一候选×对象仓位一行的`position_claims_long`长表和快照级`opportunity_matrix`。宽表必须保留全部Stage A来源列和竞争候选；长表必须保留失效旧候选、双重置信度、行情回执与`candidate_review_relation`。
11. 使用`../../scripts/tgb_delayed_disclosures.py`承接现有打码后揭名候选与append-only review；其他派生类型在通用schema迁移完成前保存为task-owned append-only artifact，不硬塞入identity表。
12. 机器只产生`candidate / unresolved / hard-rejected`。人工review追加`human-confirmed / rejected / withdrawn / source-changed`。
13. pilot先经Human Gate；全量完成后分别报告候选、确认、拒绝、未决、竞争、代码缺口、行情问题、语义queue和来源漂移。

## 下游交接

本Skill以`positions_enriched + position_claims_long + snapshot_opportunity_matrix`为正式下游read model。当用户需要一笔交易的开平段、年度总事件、账户可见资产曲线、胜率或赔率时，交给`miy-smk-broker-account-record-analysis`及其`broker-account-trade-episode-analysis`子Skill。

- Stage B不拥有“一笔交易”的跨来源定义；
- 清仓/重开claim是Stage C的输入证据，不是已实现交易本身；
- 行消失不证明清仓；明示0仓也只是截图观测端点；
- 本Skill不计算策略胜率/赔率，不从数据推断作者动机或策略有效性。

## 常用推断

- 盈亏金额/百分比反推近似金额及舍入区间；
- 市值和时间对齐价格反推100股整数倍数量；
- 市值、数量和总浮动盈亏反推持仓平均成本，但先排除累计盈亏混入已实现损益；
- 市值、数量和当日盈亏反推当日参考价；只有证明前序零仓、当日新仓且无明显减仓/回转时才升级为当日加权开仓均价；
- 前序零仓、当日新仓且无明显减仓时，交叉计算当日加权平均开仓成本；
- 同一身份链上的数量差形成加仓/减仓候选；
- 打码行与后续公开`0/0`行形成延迟揭名候选；
- 多行总市值只能约束合计时，保留合计或区间，不任意分摊。

这些公式和降级条件的单一详细owner是推断机会目录，不在本入口重复。

## 外部owner边界

- `miy-stock-data`拥有数据需求路由和统一回执；
- `kline`拥有单票历史K线与缓存；
- 本Skill不刷新或复制owner缓存；
- 日K只能验证价格区间、收盘算术和交易日，不能独立证明盘中成交或打码身份；
- canonical K线是未复权raw；若推断量来自历史成本或券商累计盈亏，必须先排除复权/公司行为/成本调整口径差异，才允许把价格冲突用于硬拒绝；
- 题材、热度和问财结果通常是exploratory/confirmatory，不是primary身份凭据。

## Green

- Stage A Green证据已绑定；
- 全部合格时间序列有处置，不合格序列说明原因；
- 每个合格时间窗的十类机会矩阵完整，每项都有`candidate / unresolved / hard-rejected / not-applicable`处置，claim kinds与candidate项一致；
- 每项claim可回链到原图SHA、转录basis、稳定token和外部回执；
- 全量DataFrame-first运行证明Stage A行守恒、未知claim对象为0，并分别导出未决MASK、竞争候选、失效旧候选、未编码候选与行情问题；
- 高风险语义队列有冻结分母、合并账本和remaining=0证明；remaining=0只描述语义审阅完成，不冒充人工确认；
- 未决被保留，没有为追求覆盖强行命名；
- 机器候选与人工状态分账；
- source-case regression与cross-author forward-test状态没有混写。

## Red

- 从OCR草稿直接推断；
- 用K线价格相似度单独给MASK命名；
- 把第一笔成交价与加权平均开仓成本混同；
- 盘中加减仓后仍机械套盈亏率公式；
- 未统一raw/qfq/hfq、公司行为和券商成本口径，就把超出未复权K线区间标成硬拒绝；
- 多匿名行任意分摊账户总额；
- 大规模任务在存在稳定结构表时仍把全部确定性公式和所有窗口重复交给模型，却没有行守恒、机会矩阵和队列分母；
- 把语义queue归零写成全部claim已人工核验，或把竞争候选压成单一最佳值；
- 覆盖确认、策略有效性、作者动机或完整账户身份；
- 用一个source case宣称跨作者validated。
