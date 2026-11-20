---
type: reference
status: structural-green
owner: taoguba-crawler
migration: source-case-regression-green / cross-author-forward-test-pending
---

# 持仓历史推断机会目录

## 使用原则

推断只能发生在Stage A Green之后。先明确`claim_kind`和必要条件，再选择计算或外部数据；不能因为某个公式能算出数，就倒推其前提一定成立。

每个合格仓位时间窗都必须建立`opportunity_matrix`，逐项处置以下类型，不得只输出最显眼的身份或清仓结论：

```text
identity
market-value
implied-price
quantity
holding-average-cost
daily-pnl-reference-price
opening-average-price
position-change
closure
reopening
```

每项只能标记为`candidate / unresolved / hard-rejected / not-applicable`之一，并保存公式、输入、前提、反证、执行者置信度、主审置信度和外部数据回执。`not-applicable`表示该时间窗本来就没有该类机会；`hard-rejected`表示表面上可套公式，但已被直接字段或市场数据否定；二者不能混用。没有矩阵项等同于没有完成审阅。

`hard-rejected`还要求比较双方处于同一可比口径。价格冲突前必须核对：行情是未复权、前复权还是后复权；截图/券商使用当时现价、历史成本还是除权除息后的调整成本；期间是否有分红、送转、配股、拆合股；当日盈亏是否混入已实现损益。任一口径未闭合时，不得仅凭“公式值不在未复权日K区间”硬拒绝，应标为`unresolved`并使用例如`adjustment-or-broker-basis-dispute`的问题码。

机械算术优先调用[`../scripts/tgb_position_inference_math.py`](../scripts/tgb_position_inference_math.py)。脚本只计算公式与舍入区间，不判断券商字段语义、是否发生交易或候选身份。

全量任务不得把本目录的重复公式逐窗交给模型重算。Stage A schema稳定且规模较大时，按[DataFrame-first合同](stage-b-dataframe-first.md)批量生成确定性候选、前提问题码和`requires_model_review / requires_market_data`队列；模型只判断高风险语义前提，主审再合并。公式候选可以保持机器未审状态，语义queue归零不能冒充人工确认。

## 1. 盈亏金额与百分比反推金额

若券商当日盈亏率满足`r = D / B`，其中`D`为当日盈亏金额、`B`为当日盈亏基准，则：

```text
base_amount = D / r
candidate_current_market_value = base_amount + D
```

界面百分比有舍入，应按显示精度计算区间。盘中加减仓、券商按更早暴露计算或费用口径不明时，必须降级为近似/不可用。

若显示百分比保留`n`位小数，先把真实百分比限制在：

```text
[displayed_pct - 0.5 * 10^-n, displayed_pct + 0.5 * 10^-n]
```

再分别计算端点并取最小/最大值。区间跨过0、金额与百分比异号、或结果为非正金额时不得机械输出。金额本身若也只显示到分，应将金额舍入误差纳入区间。单行账户且账户总市值可见时，账户总市值是更强的当前市值约束；盈亏率公式退为口径复核。

### 1.1 总浮动盈亏口径

若券商字段满足`r_f = F / C`，其中`F`为该行累计/总浮动盈亏，`C`为券商累计成本基数，则：

```text
candidate_cost_amount = F / r_f
candidate_current_market_value = candidate_cost_amount + F
```

该口径可能包含已实现盈亏。零仓后仍保留累计盈亏、当日发生过卖出/回转、或同一行历史交易不完整时，`candidate_cost_amount`不能称为当前持仓成本。

### 1.2 当日盈亏口径

若券商字段满足`r_d = D / B_d`，其中`B_d`为当日盈亏参考基数，则：

```text
candidate_daily_reference_amount = D / r_d
candidate_current_market_value = candidate_daily_reference_amount + D
```

`B_d`可能是昨收市值、当日新开仓的成交基数或券商自定义暴露，不天然等于开仓成本。只有证明“前序零仓 + 当日新仓 + 无明显减仓/回转”后，才允许把它进一步解释为当日加权开仓基数。

## 2. 当前数量与隐含价格

已知当前市值`V`和时间对齐价格`P`时：

```text
Q = V / P
```

收盘同步截图可用未复权`close`做精确算术复核；盘中截图优先使用同一时点行情，只有日K时只能要求隐含价格位于`low–high`。A股普通交易的100股整数倍可以排除候选，但零股、零仓、特殊交易或截图显示口径须单独处理。

已知数量时反向计算：

```text
implied_price = current_market_value / quantity
```

只有日K时，用`low <= implied_price <= high`做相容性判断。已知市值但只知道`low–high`时，可以给出100股整数倍数量候选区间：

```text
ceil((V / high) / 100) * 100 <= Q <= floor((V / low) / 100) * 100
```

收盘截图出现`V / close`恰为100股整数倍时，可形成较强数量候选；若结果不是整百，先检查总市值是否真的只对应该行、截图是否精确收盘、是否存在零股/转股或字段小数口径，不得擅自四舍五入成唯一股数。

## 3. 持仓平均成本与当日参考价

### 3.1 当前持仓平均成本

当前市值`V`、当前数量`Q`和浮动盈亏`F`可见，且能够排除该行累计盈亏混入已实现损益时：

```text
holding_average_cost = (V - F) / Q
```

若`r_f`语义已确认，可交叉验证：

```text
holding_average_cost = (V / Q) / (1 + r_f)
```

该值是券商成本口径下的当前持仓平均成本，不等于第一笔成交价；费用是否计入取决于券商。若零仓行仍保留浮动盈亏、日内卖出后仅余部分仓位、或公式所得成本明显超出身份已知股票的可行历史区间，应标记`hard-rejected`或`unresolved`。

### 3.2 当日盈亏参考价

当前市值`V`、数量`Q`和当日盈亏`D`可见时：

```text
daily_pnl_reference_price = (V - D) / Q
```

若`r_d`语义已确认，可交叉验证：

```text
daily_pnl_reference_price = (V / Q) / (1 + r_d)
```

隔夜持仓中它常接近昨收；当日新仓中它可能接近当日加权成交价。默认claim必须叫`daily-pnl-reference-price`，不能未经前提升级为`opening-average-price`。

## 4. 当日加权平均开仓成本

前序记录能证明零仓、当天出现新仓，且没有携带旧仓、明显盘中减仓或特殊券商口径时，可以推断券商口径下的当日加权平均开仓成本：

```text
opening_average_price ≈ (current_market_value - daily_pnl_amount) / quantity
```

若当日盈亏率`r`确以开仓成本为分母，也可交叉验证：

```text
opening_average_price ≈ current_price / (1 + r)
```

两个或更多时点独立得到相同成本区间，会加强结论。该值不是第一笔成交价；多次买入时是加权平均，费用是否计入取决于券商显示口径。

若`holding-average-cost`与`opening-average-price`略有差异，应优先检查佣金、过户费和券商累计/当日口径，而不是强行选一个覆盖另一个。两者必须作为独立claim保存。

## 5. 加仓、减仓、清仓与重新开仓

只有身份链已建立且数量可比时，才能用相邻数量差生成`position-change` claim。前一时点零仓、后一时点新仓支持`reopening`；公开`0/0`支持`closure`，但不得由行消失单独证明清仓。

## 6. 打码证券后续揭名

候选至少检查：

- 同一券商与掩码账户；
- 真实截图时间有序；
- 匿名源行和公开行可唯一分配；
- 公开行名称可见，清仓关系需要源图`0/0`；
- 盈亏、总市值、总资产和其他仓位变化相容；
- 多标的替换、行排序变化和其他候选已处理。

机器最多形成candidate。多匿名行、多公开行、时间未知、账户不一致、来源SHA漂移或竞争候选无法排除时保持`unresolved`。

## 7. 多行账户约束

账户总市值减去公开行市值可以形成匿名行合计约束；若只有一条匿名活动行，可转为该行金额候选；若有多条，除非另有独立方程，否则只保存合计或区间，不能任意分摊。

## 常见拒绝信号

- `D / r_d + D`与直接可见市值或账户约束相差显著：通常存在盘中加减仓、已实现盈亏或券商分母不是当前仓位；
- `(V - F) / Q`明显超出已知身份的历史可行价格：累计盈亏很可能混入已实现损益；
- 收盘市值除以收盘价不是可解释的股数：总市值不是单行、并非收盘同步、字段有小数/零股口径，或候选身份/数量有误；
- 同一天多个时点反推的成本基数大幅跳变，而现金或数量也变化：不能继续假设无交易；
- 公式只在把后续公开数量倒灌到早期打码行后才成立：保留条件性候选，不能改写Stage A事实。

以上是问题/排异信号，不自动等于`hard-rejected`。只有直接字段、交易路径和复权/除权/券商口径已经统一，且仍无法相容时，才可升级为硬拒绝；否则保留`unresolved`并列出需要补齐的口径证据。

## 市场数据编排

需要外部数据时，经`miy-stock-data`路由并保存完整回执：

- `kline`：交易日、canonical未复权日线区间、收盘价和相邻日连续性；如需比较历史成本或跨除权事件，必须另取相同日期的明确复权view/公司行为证据并记录口径，不能把raw与调整成本直接比较；
- `pywencai`：已有明确问句或需要候选集合时低频使用；
- 其他题材、热度或事件owner：只能补上下文，不能证明持仓身份。

不得由本Skill刷新或写入这些owner的canonical cache。

## 证据等级

```text
primary：原图、Stage A人工转录、同账户时间序列、后续公开名称
confirmatory：K线、独立公式交叉计算、账户汇总闭合
exploratory：OCR、题材/热度上下文、宽候选搜索
superseded：被完整人工转录或更强来源替代的旧窄字段记录
```

只有primary闭合并由人工review时才可`human-confirmed`；confirmatory不能独立晋级，exploratory只能发现线索。
