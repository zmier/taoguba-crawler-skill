from pathlib import Path
import tempfile
import unittest

from common.tgb_incremental import IncrementalConfig, run_incremental


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


class TestIncrementalAcceptance(unittest.TestCase):
    def test_incremental_summary_is_user_acceptance_ready(self):
        # GIVEN：一个限制为 1 页列表、1 篇详情的 incremental 配置
        list_html = (FIXTURES / "bbs_list_page_1.html").read_text(encoding="utf-8")
        article_html = (FIXTURES / "article_detail_2s8aVDvYC5w.html").read_text(encoding="utf-8")

        def fetch_html(url: str) -> str:
            return list_html if "/bbs/" in url else article_html

        with tempfile.TemporaryDirectory() as tmpdir:
            config = IncrementalConfig(
                db_path=Path(tmpdir) / "incremental.sqlite",
                max_pages=1,
                max_article_details=1,
                max_refresh_articles=0,
                comment_pages_per_article=1,
                request_interval_seconds=0,
            )

            # WHEN：运行 incremental
            summary = run_incremental(config, fetch_html=fetch_html)

            # THEN：验收摘要应覆盖增量运行的关键字段
            self.assertEqual(summary["mode"], "incremental")
            self.assertFalse(summary["full_run"])
            self.assertIn("total_pages", summary)
            self.assertIn("new_articles", summary)
            self.assertIn("updated_articles", summary)
            self.assertIn("comment_refresh_candidates", summary)
            self.assertIn("queue_done", summary)
            self.assertIn("stop_reason", summary)


if __name__ == "__main__":
    unittest.main()
