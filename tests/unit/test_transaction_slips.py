from __future__ import annotations

import unittest

from scripts.tgb_transaction_slips import (
    classify_ocr,
    mask_account_label,
    parse_position_rows,
    parse_summary_fields,
    stable_document_id,
)


def line(text: str, x: float, y: float, confidence: float = 1.0, width: float = 0.12):
    return {"text": text, "x": x, "y": y, "width": width, "height": 0.02, "confidence": confidence}


class TransactionSlipTest(unittest.TestCase):
    def test_position_snapshot_classification_and_non_slip(self):
        kind, score, basis = classify_ocr("A股交易\n总资产\n总盈亏\n总市值\n持仓/可用\n成本/现价")
        self.assertEqual(kind, "position_snapshot")
        self.assertGreaterEqual(score, 0.7)
        self.assertTrue(basis)
        self.assertEqual(classify_ocr("今日好机会：消费类。明日预判：市场情绪弱。")[0], "non_slip")

    def test_trade_and_order_classes_require_table_shape_not_one_phrase(self):
        self.assertEqual(
            classify_ocr("成交日期 成交时间 证券代码 证券名称 成交均价 成交金额")[0],
            "trade_ledger",
        )
        self.assertEqual(
            classify_ocr("委托时间 委托/成交 状态 全部成交")[0],
            "order_history",
        )
        self.assertNotEqual(
            classify_ocr("竞价最后几秒自己的成交数量出错了，开盘直接成交了。")[0],
            "trade_ledger",
        )

    def test_summary_values_follow_layout_labels(self):
        lines = [
            line("1033233.18", 0.05, 0.79), line("总资产", 0.08, 0.75),
            line("-41782.56", 0.41, 0.79), line("总盈亏", 0.44, 0.75),
            line("499554.00", 0.76, 0.79), line("总市值", 0.80, 0.75),
            line("533679.18", 0.05, 0.71), line("可取", 0.10, 0.67),
            line("533679.18", 0.41, 0.71), line("可用", 0.45, 0.67),
        ]
        values, sources = parse_summary_fields(lines)
        self.assertEqual(values["total_assets"], 1033233.18)
        self.assertEqual(values["total_profit_loss"], -41782.56)
        self.assertEqual(values["available_cash"], 533679.18)
        self.assertIn("total_market_value", sources)

    def test_position_table_keeps_field_provenance(self):
        lines = [
            line("持仓/可用", 0.59, 0.60, width=0.16),
            line("成本/现价", 0.82, 0.60, width=0.16),
            line("浦东金桥", 0.05, 0.55, width=0.16),
            line("-41782.560", 0.38, 0.55), line("26100", 0.64, 0.55), line("20.714", 0.86, 0.55),
            line("499554.000", 0.05, 0.526, width=0.18), line("-7.727%", 0.40, 0.526), line("0", 0.67, 0.526), line("19.140", 0.87, 0.526),
        ]
        rows = parse_position_rows(lines)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["stock_name"], "浦东金桥")
        self.assertEqual(rows[0]["quantity"], 26100)
        self.assertEqual(rows[0]["available_quantity"], 0)
        self.assertEqual(rows[0]["cost_price"], 20.714)
        self.assertEqual(rows[0]["current_price"], 19.14)
        self.assertEqual(rows[0]["profit_loss_pct"], -7.727)

    def test_sensitive_account_is_masked_and_id_is_stable(self):
        broker, present, masked = mask_account_label("东吴证券71126")
        self.assertEqual(broker, "东吴证券")
        self.assertTrue(present)
        self.assertEqual(masked, "***1126")
        self.assertEqual(mask_account_label("跌幅大于0:1745"), ("", False, ""))
        self.assertEqual(
            stable_document_id("1", "topic", "author_reply", "9", 1),
            stable_document_id("1", "topic", "author_reply", "9", 1),
        )


if __name__ == "__main__":
    unittest.main()
