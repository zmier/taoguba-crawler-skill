from pathlib import Path
import tempfile
import unittest

from common.tgb_full import FullRunConfig, run_full_trial
from common.tgb_storage import connect_db, count_rows


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
ERROR_HTML = """
<!DOCTYPE HTML>
<html>
  <head><title>错误页面_淘股吧</title></head>
  <body>访问太频繁，请稍后再试</body>
</html>
"""


class TestFullGuard(unittest.TestCase):
    def test_full_trial_stops_when_article_page_is_blocked(self):
        # GIVEN：列表页正常，但详情页返回错误页
        list_html = (FIXTURES / "bbs_list_page_1.html").read_text(encoding="utf-8")

        def fetch_html(url: str) -> str:
            return list_html if "/bbs/" in url else ERROR_HTML

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "guard.sqlite"
            config = FullRunConfig(
                db_path=db_path,
                total_pages=3,
                start_page=3,
                end_page=1,
                max_list_pages_per_run=1,
                max_articles_per_page=1,
                max_comment_pages_per_article=1,
                request_interval_seconds=0,
            )

            # WHEN：运行 full trial
            summary = run_full_trial(config, fetch_html=fetch_html)

            # THEN：应熔断停止，不把错误页当作详情成功入库
            self.assertEqual(summary["stop_reason"], "anti_bot_blocked")
            self.assertEqual(summary["article_details_fetched"], 0)
            self.assertEqual(summary["comment_pages_fetched"], 0)
            self.assertEqual(summary["failures"], 1)

            conn = connect_db(db_path)
            try:
                self.assertGreaterEqual(count_rows(conn, "articles"), 50)
                self.assertEqual(count_rows(conn, "comments"), 0)
                done_articles = conn.execute(
                    "select count(*) from crawl_queue where kind = 'article' and status = 'done'"
                ).fetchone()[0]
                self.assertEqual(done_articles, 0)
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
