from pathlib import Path
import tempfile
import unittest

from common.tgb_full import FullRunConfig, run_full_trial


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


class TestFullTrialAcceptance(unittest.TestCase):
    def test_full_trial_summary_is_acceptance_ready(self):
        # GIVEN：一个非常小的受控 full trial 配置
        list_html = (FIXTURES / "bbs_list_page_1.html").read_text(encoding="utf-8")
        article_html = (FIXTURES / "article_detail_2s8aVDvYC5w.html").read_text(encoding="utf-8")

        def fetch_html(url: str) -> str:
            return list_html if "/bbs/" in url else article_html

        with tempfile.TemporaryDirectory() as tmpdir:
            config = FullRunConfig(
                db_path=Path(tmpdir) / "full-trial.sqlite",
                total_pages=3,
                start_page=3,
                end_page=1,
                max_list_pages_per_run=1,
                max_articles_per_page=1,
                max_comment_pages_per_article=2,
                request_interval_seconds=0,
            )

            # WHEN：运行受控 full trial
            summary = run_full_trial(config, fetch_html=fetch_html)

            # THEN：验收摘要必须包含 TASK09 关注的质量与安全字段
            self.assertEqual(summary["mode"], "full_trial")
            self.assertFalse(summary["full_run"])
            self.assertEqual(summary["direction"], "reverse")
            self.assertEqual(summary["full_run_gate"], "manual_approval_required")
            self.assertIn("list_page_tasks_enqueued", summary)
            self.assertIn("queue_done", summary)
            self.assertIn("estimated_remaining_pages", summary)
            self.assertIn("stop_reason", summary)


if __name__ == "__main__":
    unittest.main()
