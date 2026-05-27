from pathlib import Path
import tempfile
import unittest

from common.tgb_backfill import BackfillSampleConfig, run_backfill_sample
from common.tgb_index import build_bbs_page_url
from common.tgb_storage import connect_db, count_rows


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


class TestBackfillRunner(unittest.TestCase):
    def test_run_backfill_sample_scans_oldest_page_and_comment_pages(self):
        # GIVEN：列表页 fixture 和详情页 fixture
        list_html = (FIXTURES / "bbs_list_page_1.html").read_text(encoding="utf-8")
        article_html = (FIXTURES / "article_detail_2s8aVDvYC5w.html").read_text(encoding="utf-8")
        calls: list[str] = []

        def fetch_html(url: str) -> str:
            calls.append(url)
            return list_html if "/bbs/" in url else article_html

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "backfill.sqlite"
            config = BackfillSampleConfig(
                db_path=db_path,
                total_pages=3,
                max_list_pages=1,
                max_articles_per_page=1,
                max_comment_pages_per_article=2,
                request_interval_seconds=0,
            )

            # WHEN：运行 backfill sample
            summary = run_backfill_sample(config, fetch_html=fetch_html)

            # THEN：应从最后页倒序抓，并抓评论分页
            self.assertEqual(summary["mode"], "backfill_sample")
            self.assertFalse(summary["full_run"])
            self.assertEqual(summary["direction"], "reverse")
            self.assertEqual(summary["list_pages_scanned"], 1)
            self.assertEqual(summary["article_details_fetched"], 1)
            self.assertEqual(summary["comment_pages_fetched"], 2)
            self.assertEqual(summary["failures"], 0)
            self.assertEqual(calls[0], build_bbs_page_url(3, 1))
            self.assertTrue(any(url.endswith("-2") for url in calls))

            conn = connect_db(db_path)
            try:
                self.assertGreaterEqual(count_rows(conn, "articles"), 50)
                self.assertGreaterEqual(count_rows(conn, "comments"), 50)
                page_count = conn.execute("select count(*) from article_pages").fetchone()[0]
                self.assertEqual(page_count, 2)
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
