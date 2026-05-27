from pathlib import Path
import tempfile
import unittest

from common.tgb_full import FullRunConfig, run_full_trial
from common.tgb_storage import connect_db, count_rows


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


class TestFullTrialRunner(unittest.TestCase):
    def test_run_full_trial_uses_queue_and_comment_pages(self):
        # GIVEN：列表 fixture、详情 fixture 和受控 full trial 配置
        list_html = (FIXTURES / "bbs_list_page_1.html").read_text(encoding="utf-8")
        article_html = (FIXTURES / "article_detail_2s8aVDvYC5w.html").read_text(encoding="utf-8")
        calls: list[str] = []

        def fetch_html(url: str) -> str:
            calls.append(url)
            return list_html if "/bbs/" in url else article_html

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "full-trial.sqlite"
            config = FullRunConfig(
                db_path=db_path,
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

            # THEN：应通过队列抓列表、详情和评论分页，但仍不是 production full
            self.assertEqual(summary["mode"], "full_trial")
            self.assertFalse(summary["full_run"])
            self.assertEqual(summary["full_run_gate"], "manual_approval_required")
            self.assertEqual(summary["list_pages_done"], 1)
            self.assertEqual(summary["article_details_fetched"], 1)
            self.assertEqual(summary["comment_pages_fetched"], 2)
            self.assertEqual(summary["failures"], 0)
            self.assertEqual(calls[0], "https://www.tgb.cn/bbs/3/1")
            self.assertTrue(any(url.endswith("-2") for url in calls))

            conn = connect_db(db_path)
            try:
                self.assertGreaterEqual(count_rows(conn, "articles"), 50)
                self.assertGreaterEqual(count_rows(conn, "comments"), 50)
                done = conn.execute(
                    "select count(*) from crawl_queue where status = 'done'"
                ).fetchone()[0]
                self.assertEqual(done, 4)
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
