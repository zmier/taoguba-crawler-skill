import tempfile
import unittest
from pathlib import Path

from common.tgb_full import (
    FullRunConfig,
    build_full_run_report,
    enqueue_full_trial_plan,
    plan_full_pages,
    validate_full_config,
)
from common.tgb_resume import get_queue_item
from common.tgb_storage import connect_db, count_rows, init_db


class TestFullPolicy(unittest.TestCase):
    def test_plan_full_pages_uses_reverse_range(self):
        # GIVEN：一个 full 试运行页码范围
        config = FullRunConfig(
            db_path=Path("data/full-trial.sqlite"),
            total_pages=10,
            start_page=10,
            end_page=1,
            max_list_pages_per_run=3,
        )

        # WHEN：规划 full 页码
        pages = plan_full_pages(config)

        # THEN：应从起始页倒序规划，并受 max_list_pages_per_run 限制
        self.assertEqual(pages, [10, 9, 8])

    def test_validate_full_config_requires_manual_gate_for_production(self):
        # GIVEN：一个试图进入 production full 但未人工批准的配置
        config = FullRunConfig(
            db_path=Path("data/full.sqlite"),
            total_pages=10,
            start_page=10,
            end_page=1,
            production_full=True,
            manual_approval=False,
        )

        # WHEN：校验 full 配置
        issues = validate_full_config(config)

        # THEN：应阻止长期 full 运行
        self.assertIn("manual_approval_required", issues)

    def test_enqueue_full_trial_plan_adds_list_page_tasks(self):
        # GIVEN：一个受控 full trial 配置和空队列表
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = connect_db(f"{tmpdir}/full.sqlite")
            init_db(conn)
            config = FullRunConfig(
                db_path=Path(tmpdir) / "full.sqlite",
                total_pages=5,
                start_page=5,
                end_page=1,
                max_list_pages_per_run=2,
            )

            # WHEN：入队 full trial 列表页任务
            enqueued = enqueue_full_trial_plan(conn, config)

            # THEN：应入队 2 个 list_page 任务
            self.assertEqual(enqueued, 2)
            self.assertEqual(count_rows(conn, "crawl_queue"), 2)
            self.assertIsNotNone(get_queue_item(conn, "https://www.tgb.cn/bbs/5/1"))
            self.assertIsNotNone(get_queue_item(conn, "https://www.tgb.cn/bbs/4/1"))
            conn.close()

    def test_build_full_run_report_contains_gate_and_progress(self):
        # GIVEN：一个 full trial 摘要
        summary = {
            "mode": "full_trial",
            "full_run": False,
            "list_pages_done": 2,
            "article_details_fetched": 3,
            "comment_pages_fetched": 5,
            "failures": 0,
        }

        # WHEN：构造运行报告
        report = build_full_run_report(summary)

        # THEN：报告应保留手动闸门和关键进度
        self.assertEqual(report["full_run_gate"], "manual_approval_required")
        self.assertEqual(report["list_pages_done"], 2)
        self.assertEqual(report["failures"], 0)


if __name__ == "__main__":
    unittest.main()
