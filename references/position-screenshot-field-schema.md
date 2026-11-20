---
type: reference
status: structural-green
owner: taoguba-crawler
---

# 持仓截图全字段转录合同

## 单元结构

每个原图单元格使用同一结构，避免把不可见、解析失败和真实零混为一谈：

```yaml
raw: 原图字符串或空
value: 规范化值或null
visibility: visible | source-masked | cropped | unreadable | not-shown
mask_token: stable-token-or-null
locator: {page: null, row: null, column: null, bbox: null}
review_state: ocr-draft | human-checked | unresolved
normalization_basis: image-explicit | image-plus-source-year | not-applicable | unknown
```

真实显示的`0`必须保存为数值零；只有没有值时才是`null`。

## 来源与图片字段

- `author_id`、`source_record_id`、主贴slug、reply ID、图片序号和source URL；
- `content_sha256`、MIME、原图字节数和Base64回执；
- `document_type`：`position_snapshot / trade_ledger / order_history / non_slip / unknown`；
- 设备时钟原文、截图内“持仓同步于”原文、规范化时间、时区、时间basis和年份置信度；
- 券商原文与掩码账户键；不得恢复完整账号。

图片常只显示`MM-DD HH:MM`。必须保留`image_time_raw`；发帖年份明确且无跨年冲突时可以另建规范化年份，但不能改写图片原文。月日时间被裁切时，不得只凭设备时钟或发帖时间补齐。

## 账户汇总字段

按版式存在性记录：

- 当日盈亏金额与百分比；
- 总资产；
- 总浮动盈亏或总盈亏；
- 总市值；
- 可用余额；
- 可取金额；
- 版式额外展示但不在上述集合中的账户字段，进入带原文和定位的`extra_fields`。

不能因为某券商不显示“可取”就把它写成零。

## 每一持仓行

每一行至少保存：

- `row_token`、原图行号和稳定locator；
- 股票名称、证券代码；
- 市值；
- 浮动盈亏金额与百分比；
- 当日盈亏金额与百分比；
- 持仓数量与可用数量；
- 若原图显示：成本价、当前价、买卖方向、成交数量/价格/金额和费用；
- 每个字段的单元结构、`raw_row_text`和人工review note。

底部只露出半行时也保留该行，并逐字段标`cropped`，不能整行丢弃。

## MASK代号

Stage A代号只定位“该图该行该字段被遮挡”，不宣称跨图同一：

```text
ROW-<image-stable-id>-RNN
MASK-<image-stable-id>-RNN-STOCK_NAME
MASK-<image-stable-id>-RNN-MARKET_VALUE
MASK-<image-stable-id>-RNN-HOLDING_QUANTITY
```

Stage A代号冻结后不得因后续揭名而重写。Stage B可另建包含规范化日期、券商和安全账户后缀的追踪别名，并在claim中附加候选证券代码。

## 保守状态规则

- 名称可见且持仓/可用为`0/0`：可以记录`public-zero-position`；
- 名称和持仓/可用都被遮罩：`source-masked + position_state=unknown`；
- 多条遮罩行只有账户总市值：不得把总额任意分给各行；
- OCR缺字、缺名或零解析行：不等于原图打码或无持仓；
- 原图看不清：`unreadable`，不得用上下文补成`human-checked`。

## 覆盖审计

至少分别报告：唯一持仓图分母、转录、人工排除、剩余、逐仓行数、可见性分布、时间basis、payload/row hash漂移和ledger Green。来源发生数不得冒充唯一图分母。
