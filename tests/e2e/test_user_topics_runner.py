from pathlib import Path
import tempfile
import unittest

from common.tgb_user_topics import UserTopicsConfig, run_user_topics
from common.tgb_storage import connect_db, count_rows


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


class TestUserTopicsRunner(unittest.TestCase):
    def test_run_user_topics_writes_user_topic_index_to_sqlite(self):
        # GIVEN：一个用户 latest-topic HTML fixture 和空数据库
        article_html = (FIXTURES / "article_detail_2s8aVDvYC5w.html").read_text(encoding="utf-8")
        user_topic_html = """
        <html>
          <head><title>柏拉爱空_最新主帖_博客_淘股吧</title></head>
          <body>
            <form name="nameFrm">
              <input type="hidden" name="pageNo" value="1"/>
            </form>
            <script>function gotoPage(pageNo){ var pageNum = 1; }</script>
            <div class="topic-row">
              <a href="/a/2s8aVDvYC5w" title="指数这样的图形，怕不怕周四的剧本？">指数这样的图形，怕不怕周四的剧本？</a>
              <a href="/blog/252069">柏拉爱空</a>
              <span>50 / 1000</span>
              <span>05-27 10:00</span>
            </div>
          </body>
        </html>
        """

        def fetch_html(url: str) -> str:
            if "moreTopic" in url:
                return user_topic_html
            return article_html

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "user-topic.sqlite"
            config = UserTopicsConfig(
                db_path=db_path,
                user_id="252069",
                max_pages=1,
                fetch_article_details=True,
                max_article_details=1,
                comment_pages_per_article=1,
                request_interval_seconds=0,
            )

            # WHEN：运行用户主帖抓取小闭环
            summary = run_user_topics(config, fetch_html=fetch_html)

            # THEN：应写入索引、详情、评论，并返回用户页摘要
            conn = connect_db(db_path)
            try:
                self.assertEqual(count_rows(conn, "articles"), 1)
                self.assertEqual(count_rows(conn, "comments"), 50)
                self.assertEqual(count_rows(conn, "failures"), 0)
            finally:
                conn.close()
            self.assertEqual(summary["mode"], "user_topics")
            self.assertEqual(summary["user_id"], "252069")
            self.assertEqual(summary["total_pages"], 1)
            self.assertEqual(summary["planned_pages"], [1])
            self.assertEqual(summary["article_details_fetched"], 1)

    def test_run_user_topics_details_only_resumes_from_existing_index(self):
        # GIVEN：先只抓用户索引，再从数据库续抓详情
        article_html = (FIXTURES / "article_detail_2s8aVDvYC5w.html").read_text(encoding="utf-8")
        user_topic_html = """
        <html>
          <body>
            <input type="hidden" name="pageNo" value="1"/>
            <script>var pageNum = 1;</script>
            <div class="topic-row">
              <a href="/a/2s8aVDvYC5w" title="指数这样的图形，怕不怕周四的剧本？">指数这样的图形，怕不怕周四的剧本？</a>
              <a href="/blog/252069">柏拉爱空</a>
              <span>50 / 1000</span>
              <span>05-27 10:00</span>
            </div>
          </body>
        </html>
        """

        def fetch_html(url: str) -> str:
            if "moreTopic" in url:
                return user_topic_html
            return article_html

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "user-topic.sqlite"
            index_config = UserTopicsConfig(
                db_path=db_path,
                user_id="252069",
                max_pages=1,
                fetch_article_details=False,
                request_interval_seconds=0,
            )
            run_user_topics(index_config, fetch_html=fetch_html)

            # WHEN：使用 details_only 从已有索引续抓详情
            detail_config = UserTopicsConfig(
                db_path=db_path,
                user_id="252069",
                details_only=True,
                fetch_article_details=True,
                max_article_details=1,
                comment_pages_per_article=1,
                request_interval_seconds=0,
            )
            summary = run_user_topics(detail_config, fetch_html=fetch_html)

            # THEN：不需要重扫列表页，也能抓到详情和评论
            conn = connect_db(db_path)
            try:
                self.assertEqual(count_rows(conn, "articles"), 1)
                self.assertEqual(count_rows(conn, "comments"), 50)
            finally:
                conn.close()
            self.assertEqual(summary["list_pages_fetched"], 0)
            self.assertEqual(summary["article_details_fetched"], 1)


if __name__ == "__main__":
    unittest.main()
