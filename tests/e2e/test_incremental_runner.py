from pathlib import Path
import tempfile
import unittest

from common.tgb_incremental import IncrementalConfig, run_incremental
from common.tgb_storage import connect_db, count_rows


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


class TestIncrementalRunner(unittest.TestCase):
    def test_run_incremental_discovers_articles_and_saves_comments(self):
        # GIVEN：一页列表 fixture 和一页带评论详情 fixture
        list_html = (FIXTURES / "bbs_list_page_1.html").read_text(encoding="utf-8")
        article_html = (FIXTURES / "article_detail_2s8aVDvYC5w.html").read_text(encoding="utf-8")

        def fetch_html(url: str) -> str:
            return list_html if "/bbs/" in url else article_html

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "incremental.sqlite"
            config = IncrementalConfig(
                db_path=db_path,
                max_pages=1,
                max_article_details=1,
                max_refresh_articles=0,
                comment_pages_per_article=1,
                request_interval_seconds=0,
            )

            # WHEN：运行 incremental 小闭环
            summary = run_incremental(config, fetch_html=fetch_html)

            # THEN：应发现新帖、抓详情、写评论，并且明确不是 full
            self.assertEqual(summary["mode"], "incremental")
            self.assertFalse(summary["full_run"])
            self.assertEqual(summary["list_pages_scanned"], 1)
            self.assertGreaterEqual(summary["new_articles"], 50)
            self.assertEqual(summary["article_details_fetched"], 1)
            self.assertEqual(summary["comments_saved"], 50)
            self.assertEqual(summary["failures"], 0)
            self.assertTrue(summary["stop_reason"])

            conn = connect_db(db_path)
            try:
                self.assertGreaterEqual(count_rows(conn, "articles"), 50)
                self.assertEqual(count_rows(conn, "comments"), 50)
                done_count = conn.execute(
                    "select count(*) from crawl_queue where status = 'done'"
                ).fetchone()[0]
                self.assertEqual(done_count, 1)
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
