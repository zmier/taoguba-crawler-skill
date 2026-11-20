from __future__ import annotations

import base64
import hashlib
import sqlite3
import unittest

from scripts.tgb_position_visual_reviews import (
    VISUAL_SCHEMA_SQL,
    export_review_queue,
    import_visual_reviews,
    init_schema,
    review_coverage,
    validate_visual_review,
)


AUTHOR_ID = "6724235"
REVIEWED_AT = "2026-08-26T09:00:00+08:00"


def image_sha(seed: str) -> tuple[str, str]:
    raw = seed.encode("utf-8")
    return hashlib.sha256(raw).hexdigest(), base64.b64encode(raw).decode("ascii")


def review(
    *,
    content_sha256: str,
    document_id: str,
    layout_state: str,
    rows: list[dict[str, object]],
) -> dict[str, object]:
    visible_rows = sum(row["identity_state"] == "visible" for row in rows)
    masked_active_rows = sum(
        row["identity_state"] == "source-masked"
        and row["position_state"] == "active"
        for row in rows
    )
    visible_closed_rows = sum(
        row["identity_state"] == "visible"
        and row["position_state"] == "closed"
        for row in rows
    )
    unreadable_rows = sum(row["identity_state"] == "unreadable" for row in rows)
    return {
        "content_sha256": content_sha256,
        "representative_document_id": document_id,
        "statement_time": "2024-03-06T15:00:00+08:00",
        "account_key": "东吴证券|***1126",
        "layout_state": layout_state,
        "visible_rows": visible_rows,
        "masked_active_rows": masked_active_rows,
        "visible_closed_rows": visible_closed_rows,
        "unreadable_rows": unreadable_rows,
        "rows": rows,
        "reviewed_by": "unit-reviewer",
        "reviewed_at": REVIEWED_AT,
        "review_note": "人工核对原图；OCR不作为身份依据。",
    }


class PositionVisualReviewTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute(
            "create table image_assets (content_sha256 text primary key, base64_data text not null)"
        )
        self.conn.execute(
            """
            create table transaction_slip_documents (
              document_id text primary key,
              author_id text not null,
              content_sha256 text not null,
              statement_date text not null default '',
              source_created_at text not null default '',
              source_url text not null default '',
              broker_name_ocr text not null default '',
              account_label_masked text not null default '',
              document_type text not null
            )
            """
        )
        init_schema(self.conn)

    def tearDown(self) -> None:
        self.conn.close()

    def add_position_document(
        self,
        *,
        document_id: str,
        seed: str,
        statement_date: str = "2024-03-06",
    ) -> str:
        content_sha256, encoded = image_sha(seed)
        self.conn.execute(
            "insert into image_assets(content_sha256,base64_data) values (?,?)",
            (content_sha256, encoded),
        )
        self.conn.execute(
            """
            insert into transaction_slip_documents(
              document_id,author_id,content_sha256,statement_date,source_created_at,
              source_url,broker_name_ocr,account_label_masked,document_type
            ) values (?,?,?,?,?,?,?,?,?)
            """,
            (
                document_id,
                AUTHOR_ID,
                content_sha256,
                statement_date,
                statement_date + "T15:00:00+08:00",
                "https://www.tgb.cn/a/" + document_id,
                "东吴证券",
                "***1126",
                "position_snapshot",
            ),
        )
        self.conn.commit()
        return content_sha256

    def test_masked_active_and_visible_closed_reviews_are_legal(self) -> None:
        masked_sha = self.add_position_document(document_id="masked", seed="masked")
        closed_sha = self.add_position_document(document_id="closed", seed="closed")
        masked = review(
            content_sha256=masked_sha,
            document_id="masked",
            layout_state="masked-active",
            rows=[
                {
                    "visual_row_no": 1,
                    "identity_state": "source-masked",
                    "position_state": "active",
                    "holding_quantity": 100,
                    "available_quantity": 100,
                    "locator": {"row": 1},
                }
            ],
        )
        closed = review(
            content_sha256=closed_sha,
            document_id="closed",
            layout_state="fully-visible",
            rows=[
                {
                    "visual_row_no": 1,
                    "identity_state": "visible",
                    "position_state": "closed",
                    "stock_code": "600000",
                    "stock_name": "浦发银行",
                    "holding_quantity": 0,
                    "available_quantity": 0,
                    "locator": {"row": 1},
                }
            ],
        )

        # GIVEN 两种合法源图状态 WHEN 追加人工审阅 THEN 两条派生审阅均可落库。
        result = import_visual_reviews(
            self.conn, author_id=AUTHOR_ID, reviews=[masked, closed]
        )

        self.assertEqual(result["imported"], 2)
        self.assertEqual(result["rejected"], 0)
        self.assertEqual(
            self.conn.execute(
                "select count(*) from transaction_slip_visual_position_rows"
            ).fetchone()[0],
            2,
        )

    def test_masked_row_cannot_store_stock_identity(self) -> None:
        content_sha256 = self.add_position_document(document_id="masked-name", seed="masked-name")
        invalid = review(
            content_sha256=content_sha256,
            document_id="masked-name",
            layout_state="masked-active",
            rows=[
                {
                    "visual_row_no": 1,
                    "identity_state": "source-masked",
                    "position_state": "active",
                    "stock_name": "不应回填",
                    "locator": {"row": 1},
                }
            ],
        )

        # GIVEN 源图已打码 WHEN 尝试补入股票名 THEN 校验必须拒绝。
        with self.assertRaisesRegex(ValueError, "masked_row_cannot_store_public_identity"):
            validate_visual_review(invalid)

    def test_masked_positions_can_preserve_unknown_row_state(self) -> None:
        content_sha256 = self.add_position_document(
            document_id="masked-unknown", seed="masked-unknown"
        )
        payload = review(
            content_sha256=content_sha256,
            document_id="masked-unknown",
            layout_state="masked-positions",
            rows=[
                {
                    "visual_row_no": 1,
                    "identity_state": "source-masked",
                    "position_state": "unknown",
                    "holding_quantity": None,
                    "available_quantity": None,
                    "locator": {"row": 1},
                }
            ],
        )

        # GIVEN 名称和数量都被源图遮罩 WHEN 活动/清仓不可判 THEN 保留unknown合法。
        result = import_visual_reviews(
            self.conn, author_id=AUTHOR_ID, reviews=[payload]
        )

        self.assertEqual(result["imported"], 1)
        self.assertEqual(result["rejected"], 0)

    def test_unknown_statement_time_cannot_borrow_source_time(self) -> None:
        content_sha256 = self.add_position_document(
            document_id="unknown-time", seed="unknown-time"
        )
        payload = review(
            content_sha256=content_sha256,
            document_id="unknown-time",
            layout_state="masked-positions",
            rows=[
                {
                    "visual_row_no": 1,
                    "identity_state": "source-masked",
                    "position_state": "unknown",
                    "locator": {"row": 1},
                }
            ],
        )
        payload["statement_time_basis"] = "unknown"
        payload["statement_time"] = ""
        validate_visual_review(payload)
        payload["statement_time"] = "2024-03-06T15:00:00+08:00"

        # GIVEN 原图无时间 WHEN 尝试借来源发表时间 THEN 必须拒绝伪装成截图时间。
        with self.assertRaisesRegex(ValueError, "unknown_statement_time_must_be_empty"):
            validate_visual_review(payload)

    def test_visible_closed_requires_both_position_quantities_zero(self) -> None:
        content_sha256 = self.add_position_document(document_id="closed-nonzero", seed="closed-nonzero")
        for field in ("holding_quantity", "available_quantity"):
            with self.subTest(field=field):
                row = {
                    "visual_row_no": 1,
                    "identity_state": "visible",
                    "position_state": "closed",
                    "stock_code": "600000",
                    "stock_name": "浦发银行",
                    "holding_quantity": 0,
                    "available_quantity": 0,
                    "locator": {"row": 1},
                }
                row[field] = 1
                invalid = review(
                    content_sha256=content_sha256,
                    document_id="closed-nonzero",
                    layout_state="fully-visible",
                    rows=[row],
                )

                # GIVEN 可见清仓行 WHEN 任一持仓数量非零 THEN 不可称为closed。
                with self.assertRaisesRegex(
                    ValueError, "visible_closed_row_requires_zero_position"
                ):
                    validate_visual_review(invalid)

    def test_identical_review_is_append_idempotent(self) -> None:
        content_sha256 = self.add_position_document(document_id="same", seed="same")
        payload = review(
            content_sha256=content_sha256,
            document_id="same",
            layout_state="masked-active",
            rows=[
                {
                    "visual_row_no": 1,
                    "identity_state": "source-masked",
                    "position_state": "active",
                    "locator": {"row": 1},
                }
            ],
        )

        # GIVEN 同一证据包 WHEN 连续导入两次 THEN 第二次只报告duplicate，不覆写首条审阅。
        first = import_visual_reviews(self.conn, author_id=AUTHOR_ID, reviews=[payload])
        second = import_visual_reviews(self.conn, author_id=AUTHOR_ID, reviews=[payload])

        self.assertEqual((first["imported"], first["duplicates"]), (1, 0))
        self.assertEqual((second["imported"], second["duplicates"]), (0, 1))
        self.assertEqual(
            self.conn.execute(
                "select count(*) from transaction_slip_visual_reviews"
            ).fetchone()[0],
            1,
        )

    def test_coverage_deduplicates_by_unique_image_sha(self) -> None:
        content_sha256 = self.add_position_document(document_id="first", seed="shared-image")
        self.conn.execute(
            """
            insert into transaction_slip_documents(
              document_id,author_id,content_sha256,statement_date,source_created_at,
              source_url,broker_name_ocr,account_label_masked,document_type
            ) values (?,?,?,?,?,?,?,?,?)
            """,
            (
                "second",
                AUTHOR_ID,
                content_sha256,
                "2024-03-07",
                "2024-03-07T15:00:00+08:00",
                "https://www.tgb.cn/a/second",
                "东吴证券",
                "***1126",
                "position_snapshot",
            ),
        )
        self.conn.commit()
        payload = review(
            content_sha256=content_sha256,
            document_id="first",
            layout_state="masked-active",
            rows=[
                {
                    "visual_row_no": 1,
                    "identity_state": "source-masked",
                    "position_state": "active",
                    "locator": {"row": 1},
                }
            ],
        )
        import_visual_reviews(self.conn, author_id=AUTHOR_ID, reviews=[payload])

        # GIVEN 同一图被两个来源引用 WHEN 统计覆盖 THEN 分母和已审均按唯一SHA计。
        coverage = review_coverage(self.conn, AUTHOR_ID)

        self.assertEqual(coverage["unique_position_images"], 1)
        self.assertEqual(coverage["human_reviewed_unique_images"], 1)
        self.assertEqual(coverage["remaining_unique_images"], 0)

    def test_export_queue_prioritizes_later_images(self) -> None:
        early_sha = self.add_position_document(
            document_id="early", seed="early", statement_date="2018-10-31"
        )
        late_sha = self.add_position_document(
            document_id="late", seed="late", statement_date="2018-11-01"
        )

        # GIVEN 早晚两张未审图 WHEN 导出队列 THEN 晚期图在前并带late-priority标记。
        queue = export_review_queue(self.conn, author_id=AUTHOR_ID)

        self.assertEqual([item["content_sha256"] for item in queue["items"]], [late_sha, early_sha])
        self.assertEqual([item["priority"] for item in queue["items"]], ["late-priority", "earlier"])
        self.assertEqual(queue["counts"], {"all": 2, "late_priority": 1, "earlier": 1, "already_reviewed": 0})

    def test_latest_review_orders_absolute_time_across_offsets(self) -> None:
        content_sha256 = self.add_position_document(document_id="offset", seed="offset")
        first = review(content_sha256=content_sha256, document_id="offset", layout_state="masked-active", rows=[{
            "visual_row_no": 1, "identity_state": "source-masked", "position_state": "active", "locator": {"row": 1}
        }])
        import_visual_reviews(self.conn, author_id=AUTHOR_ID, reviews=[first])
        later = dict(first)
        later["reviewed_at"] = "2026-08-26T10:00:00+00:00"
        later["review_note"] = "later offset review"
        later["layout_state"] = "masked-positions"
        later["masked_active_rows"] = 0
        later["rows"] = [{"visual_row_no": 1, "identity_state": "source-masked", "position_state": "unknown", "locator": {"row": 1}}]
        import_visual_reviews(self.conn, author_id=AUTHOR_ID, reviews=[later])
        coverage = review_coverage(self.conn, AUTHOR_ID)
        self.assertEqual(coverage["layout_state_counts"], {"masked-positions": 1})

    def test_layout_state_migration_preserves_append_only_reviews(self) -> None:
        conn = sqlite3.connect(":memory:")
        try:
            conn.execute(
                "create table image_assets (content_sha256 text primary key, base64_data text not null)"
            )
            legacy_sql = VISUAL_SCHEMA_SQL.replace(
                ",'masked-positions'", ""
            )
            conn.executescript(legacy_sql)
            conn.execute(
                "insert into image_assets values (?,?)", ("sha-old", "b2xk")
            )
            conn.execute(
                """
                insert into transaction_slip_visual_reviews values (
                  'review-old','6724235','sha-old','doc-old',
                  '2024-03-06T15:00:00+08:00','东吴证券|***1126',
                  'masked-active',0,1,0,0,'{}','evidence-sha',
                  'reviewer','2026-08-26T09:00:00+08:00','note',
                  'legacy','2026-08-26T01:00:00+00:00'
                )
                """
            )
            conn.execute(
                """
                insert into transaction_slip_visual_position_rows values (
                  'review-old',1,'source-masked','active','','',
                  null,null,null,null,'{}',''
                )
                """
            )
            conn.commit()

            # GIVEN 旧CHECK约束数据库 WHEN 初始化新版本 THEN 原追加事件不丢失且新状态可用。
            init_schema(conn)

            self.assertEqual(
                conn.execute(
                    "select count(*) from transaction_slip_visual_reviews"
                ).fetchone()[0],
                1,
            )
            sql = conn.execute(
                "select sql from sqlite_master where name='transaction_slip_visual_reviews'"
            ).fetchone()[0]
            self.assertIn("masked-positions", sql)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
