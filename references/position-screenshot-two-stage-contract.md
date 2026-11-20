---
type: reference
status: structural-green
owner: taoguba-crawler
migration: source-case-regression-green / cross-author-forward-test-pending
---

# TGB实盘截图两阶段合同

## 定位

本合同是`taoguba-crawler`从目标作者本人发布的券商实盘截图形成持仓记录的单一语义owner。来源获取、图片Base64归档、截图事实转录和跨图推断是不同层，不得互相覆盖：

```text
作者来源与原图
→ Stage A：原图全字段转录
→ Stage A Green
→ Stage B：跨图与市场数据辅助推断
→ append-only claims + 人工裁决
```

原图字节、Base64、SHA-256和来源定位始终是canonical source。OCR、人工转录和推断都是派生层。

## 前置条件

- 目标作者以不可变数字型`user_id`固定；
- 主贴/本人回复文本层已达到请求范围Green；
- 仅目标作者本人图片进入媒体库，第三方图片为0；
- 图片按内容SHA-256去重，来源发生另存；
- 可得原图均能Base64往返并复算SHA；上游不可得图片作为来源缺口单列。

前置条件不满足时，只能报告缺口，不得用OCR预览、缩略图或第三方转载替代原图。

## Stage A：原图全字段转录

Stage A对每个唯一`position_snapshot`逐图人工阅读，记录原图能表达的全部账户汇总和逐仓字段。OCR可以定位、预填和挑战人工结果，但不能直接产生`human-checked`事实。

必须遵守：

- 原始字符串、规范化数值、可见性、定位和复核状态分开保存；
- `visible / source-masked / cropped / unreadable / not-shown`不是普通空值；
- 每个持仓行和被遮字段获得稳定代号；
- 图片显示的月日时间与来源推定年份分账；
- 名称与持仓/可用同时被遮罩时保持`position_state=unknown`，不得由列表存在、盈亏或多行账户总市值强行升级；
- 阶段A不连接不同截图中的MASK，也不推断股票、数量、价格或动机。

完整字段见[字段合同](position-screenshot-field-schema.md)。

Stage A Green：

```text
unique_position_images denominator frozen
+ 每张唯一图都有人工转录或有理由的人工排除
+ 账户/逐仓字段、可见性和MASK完整
+ source SHA与转录basis无漂移
+ remaining=0且ledger Green
```

首个新账号应先做小型Human Gate：覆盖完整可见、混合打码和裁切/不可读等代表版式。题数由实际版式簇决定；来源案例中的3图只是一种已通过配置，不是不可变常数。

## Stage B：持仓历史推断

Stage B只消费达到Green的Stage A记录，不得读取OCR草稿后绕过人工转录。它按作者、券商/掩码账户和真实截图时间组织序列，生成而不是覆盖事实的推断claim。

允许的推断包括：

- 打码证券与后续公开名称的候选关系；
- 当前市值、隐含价格、持仓数量和数量变化；
- 当前持仓平均成本、当日盈亏参考价、满足严格前提后的当日加权平均开仓成本；
- 加仓、减仓、清仓和重新开仓；
- 可被账户汇总约束的多行金额区间；
- 无法唯一分配时的明确`unresolved`。

计算条件、公式与降级边界见[推断机会目录](position-inference-opportunities.md)。

每个claim至少包含：

```yaml
claim_kind: identity | quantity | market-value | implied-price | holding-average-cost | daily-pnl-reference-price | opening-average-price | position-change | closure | reopening
subject_tokens: []
candidate: null
estimate: null
range: null
unit: null
assumptions: []
supporting_evidence: []
counterevidence: []
external_evidence_receipts: []
confidence: high | medium | low | unresolved
machine_state: candidate | unresolved | hard-rejected
review_state: unreviewed | human-confirmed | rejected | withdrawn | source-changed
basis_sha256: sha256
```

每个合格仓位时间窗还必须保存覆盖全部claim kind的`opportunity_matrix`。矩阵项的处置为`candidate / unresolved / hard-rejected / not-applicable`；已有claim只代表`candidate`项，不能代替其余机会的处置。每项同时保存执行者置信度与主审置信度。没有明确处置的类型视为漏审，Stage B不得Green。

机器可以排序、排除和形成候选，不能自行写`human-confirmed`。原图、转录或外部证据SHA漂移时须fail closed。

Stage B Green不是“所有MASK都猜出答案”，而是：所有合格序列被审阅；每个时间窗的机会矩阵完整；每个候选、拒绝、未决和不适用都有可回链basis；确认由人工追加；未决没有被总成功隐藏。

首个新账号应先冻结一段连续时间序列做Human Gate，再解锁全量。窗口长度由截图密度和持仓变化决定；来源案例中的5个交易日不是通用硬编码。

### 全量执行形态

小型pilot可以直接逐窗审阅。全量任务若已有稳定Stage A结构表、窗口数量较多且机械公式高度重复，应采用[DataFrame-first合同](stage-b-dataframe-first.md)：先投影Stage A快照/仓位、安全时序链接、确定性候选和十类机会矩阵，再仅把身份链、开仓/重新开仓前提、竞争候选与异常口径送入高风险语义队列。

全量输出至少包含一仓一行且保留全部Stage A来源列的`positions_enriched`、一候选×对象仓位一行的`position_claims_long`、完整`opportunity_matrix`、未决/竞争/失效/未编码/行情问题导出，以及证明语义队列分母和remaining=0的审计。remaining=0只证明高风险语义项全部被处置，不等于机械候选已人工核验，更不等于`human-confirmed`。

## 外部数据owner边界

Stage B需要行情或候选集合时，通过`miy-stock-data`路由，不直接复制provider逻辑或缓存：

```text
单票历史日线、价格区间、收盘算术 → kline
已知问句或候选集合                   → pywencai
题材/热度上下文                      → 对应owner，仅作上下文
```

外部数据只辅助验证或排除候选。日K不能单独证明盘中成交、持仓身份或作者意图；历史日期不得用今天spot代替。每次使用须保存owner、capability、请求/实际日期、来源、SHA、复权、单位、fallback和失败回执。本TASK不得写外部owner缓存。

## 执行模式

- `extract-only`：只完成媒体前置、OCR草稿和Stage A；不生成持仓历史推断。
- `infer-with-evidence`：必须先证明Stage A Green，再执行Stage B和人工裁决。

如果用户只要求OCR可搜索文本，仍使用`tgb-author-transaction-slips`，不得暗示已经完成人工持仓记录。

## 不可泛化

- 不恢复完整账户身份；只保留原图已有掩码和安全账户键；
- 不把盈亏截图当成交易真实性或策略有效性证明；
- 不从图片关系推断作者隐藏动机；作者动机只接受带reply ID/时间的原话且不扩大范围；
- 不把来源案例中的作者、日期、股票、数量、金额或Gate题数写成通用规则；
- 不把`structural-green`写成跨作者`validated`。
