from pathlib import Path
import tempfile
import unittest

from common.tgb_backfill import BackfillSampleConfig, run_backfill_sample


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


class TestBackfillAcceptance(unittest.TestCase):
    def test_backfill_sample_summary_has_full_run_gate(self):
        # GIVEN：一个非常小的 backfill sample 配置
        list_html = (FIXTURES / "bbs_list_page_1.html").read_text(encoding="utf-8")
        article_html = (FIXTURES / "article_detail_2s8aVDvYC5w.html").read_text(encoding="utf-8")

        def fetch_html(url: str) -> str:
            return list_html if "/bbs/" in url else article_html

        with tempfile.TemporaryDirectory() as tmpdir:
            config = BackfillSampleConfig(
                db_path=Path(tmpdir) / "backfill.sqlite",
                total_pages=3,
                max_list_pages=1,
                max_articles_per_page=1,
                max_comment_pages_per_article=2,
                request_interval_seconds=0,
            )

            # WHEN：运行 backfill sample
            summary = run_backfill_sample(config, fetch_html=fetch_html)

            # THEN：摘要必须明确这是 sample，不是长期 full 全量运行
            self.assertEqual(summary["mode"], "backfill_sample")
            self.assertFalse(summary["full_run"])
            self.assertEqual(summary["direction"], "reverse")
            self.assertIn("full_run_gate", summary)
            self.assertIn("stop_reason", summary)
            self.assertEqual(summary["full_run_gate"], "manual_approval_required")


if __name__ == "__main__":
    unittest.main()
