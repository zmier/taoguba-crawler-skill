---
name: tgb-position-screenshot-transcription
description: 将淘股吧目标作者本人发布的券商持仓、账户和交割单截图逐图转录为来源忠实、字段级可见性明确、可审计的持仓快照。用于“识别实盘截图”“把持仓图读成完整文本/结构化记录”“区分可见、打码、裁切和不可读字段”或在任何跨图推断前完成Stage A；不负责猜测打码股票、数量或开仓价。
---

# TGB持仓截图全字段转录

## 目标与边界

把原图直接表达的全部信息转成可回链的人工转录。原图/Base64/SHA是canonical；OCR只是`ocr-draft`，不能替代逐图阅读，也不能根据上下文补不可见字段。

开始前必须读取：

- [`../../references/position-screenshot-two-stage-contract.md`](../../references/position-screenshot-two-stage-contract.md)：Stage A/Stage B边界；
- [`../../references/position-screenshot-field-schema.md`](../../references/position-screenshot-field-schema.md)：账户、逐仓、单元格和MASK字段。

## 输入前置

- 数字型目标`user_id`已冻结；
- 按批次冻结来源范围。发帖批次使用主帖与本人回帖图库，赛事批次使用已核对参赛者的比赛原图索引、覆盖回执与只读原图库；
- 原图按SHA-256去重，来源发生、reply ID和图片位置仍可回链；
- 上游不可得图片已单列，不伪装为OCR或人工完成。

前置不满足时，返回缺口并停在媒体层。

## 执行模式

- `pilot`：选择覆盖真实版式簇的少量图片，冻结字段、MASK和Human Gate口径。
- `full-transcription`：Gate通过后，对全部唯一`position_snapshot`逐图转录。

比赛批次运行 `python scripts/tgb_match_transcription.py --user-id "$USER_ID" --match-dir "$MATCH_DIR" --output-db "$RESEARCH_DB"`（从爬虫根目录运行）。`--max-assets 0` 仅准备队列，默认复用已成功的 OCR 并识别其余图片。输出库与原档分开。按 `stage_a_review_queue` 选取不同版式逐图复核，用 `content_sha256` 回查 `match_placements` 中各场出处以及来源库 `files.sha256` 的原件。来源缺图按位置留空。报单归属日与提交时间各自保留；图上明示日期由审图时登记。跨批次按 SHA 复用同文件的阅读，对不同字节的疑似同图另记匹配依据。各批次保留原分母和人工状态。

## 流程

1. 使用`../../scripts/tgb_transaction_slips.py`对唯一资产做OCR、分类和可空结构草稿；已有OCR可用`--reclassify-only`复用。
2. 冻结唯一持仓图分母，来源发生数不得作为人工审阅分母。
3. 按字段合同逐图人工读取账户汇总、时间、券商/掩码账户和每条持仓。
4. 对每个单元保存原文、规范化值、可见性、locator、review状态；真实零与空值分开。
5. 对打码行和打码字段生成稳定Stage A代号；不连接不同截图中的代号。
6. 以append-only事件保存人工转录；修订新增事件，不覆盖历史或OCR/source表。
7. 运行覆盖与hash审计，分别报告转录、人工排除、剩余、行数、可见性和时间basis。

`../../scripts/tgb_position_visual_reviews.py`仍可用于现有窄字段视觉队列和兼容账本；当任务要求全字段转录时，必须使用字段合同承接全部单元，不得因为兼容表列较少而丢字段。

## 时间与MASK

- 图片月日时间原文永久保留；只有来源年份明确且无跨年冲突时，才另建带basis的规范化年份。
- 图片月日被裁切时，不能用发帖时间补成`image-explicit`。
- 名称与持仓/可用同时被遮罩时保持`source-masked + position_state=unknown`。
- 后续揭名不得反写Stage A代号和原图打码事实。

## 输出

- 唯一图人工转录ledger；
- 账户级与逐仓字段记录；
- 字段级可见性、原文、规范化值、MASK和locator；
- source/payload/row SHA回执；
- 覆盖审计与Human Gate材料。

## Green

- pilot已经人工决定，或明确标记为尚未解锁全量；
- 全量模式下，每张唯一持仓图有人工转录或有理由的人工排除；
- 账户和逐仓字段没有因OCR/表结构缺列而静默丢失；
- `remaining=0`、basis无漂移、ledger Green；
- 没有Stage B推断混入Stage A事实。

## Red

- OCR零行等于无持仓或原图打码；
- 用盈亏、文件名、股票上下文或行情补出不可见字段；
- 把裁切字段写成零；
- 恢复完整账户身份；
- 只审晚期图片却声称全量；
- 在Stage A中改名MASK或写入候选股票。
