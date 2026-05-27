from pathlib import Path
import tempfile
import unittest

from common.tgb_sample import SampleConfig, run_sample
from common.tgb_storage import connect_db, count_rows


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


class TestSampleRunner(unittest.TestCase):
    def test_run_sample_writes_small_fixture_loop_to_sqlite(self):
        # GIVEN：列表页与详情页 fixture，以及一个空的临时数据库
        list_html = (FIXTURES / "bbs_list_page_1.html").read_text(encoding="utf-8")
        article_html = (FIXTURES / "article_detail_2s8aVDvYC5w.html").read_text(encoding="utf-8")

        def fetch_html(url: str) -> str:
            if "/bbs/" in url:
                return list_html
            return article_html

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "sample.sqlite"
            config = SampleConfig(
                db_path=db_path,
                list_urls=["https://www.tgb.cn/bbs/1/1"],
                max_articles=1,
                comment_pages_per_article=1,
                request_interval_seconds=0,
            )

            # WHEN：运行 sample 小闭环
            summary = run_sample(config, fetch_html=fetch_html)

            # THEN：应写入索引、1 篇详情、评论和完成态队列
            conn = connect_db(db_path)
            try:
                self.assertGreaterEqual(count_rows(conn, "articles"), 50)
                self.assertEqual(count_rows(conn, "comments"), 50)
                self.assertEqual(count_rows(conn, "failures"), 0)
                done_count = conn.execute(
                    "select count(*) from crawl_queue where status = 'done'"
                ).fetchone()[0]
            finally:
                conn.close()
            self.assertEqual(done_count, 1)
            self.assertEqual(summary["mode"], "sample")
            self.assertEqual(summary["article_details_fetched"], 1)
            self.assertEqual(summary["comments_saved"], 50)
            self.assertTrue(Path(summary["db_path"]).exists())


if __name__ == "__main__":
    unittest.main()
