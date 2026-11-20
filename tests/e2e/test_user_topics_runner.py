from pathlib import Path
import tempfile
import unittest

from common.tgb_user_topics import UserTopicsConfig, run_user_topics
from common.tgb_storage import connect_db, count_rows


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


class TestUserTopicsRunner(unittest.TestCase):
    def test_main_post_only_mode_does_not_parse_or_persist_comments(self):
        user_topic_html = """
        <html><body>
          <input type="hidden" name="pageNo" value="1"/>
          <script>var pageNum = 1;</script>
          <div class="topic-row">
            <a href="/a/largepost" title="大型实盘楼">大型实盘楼</a>
            <a href="/blog/1116585">涅盘重升</a>
            <span>83199 / 100000</span><span>08-25 18:46</span>
          </div>
        </body></html>
        """
        article_html = """
        <html><body>
          <div id="gioMsg" username="涅盘重升" userid="1116585"></div>
          <h1 id="stockTitle">大型实盘楼</h1>
          <div id="first">认证主贴正文</div>
          <span>浏览 100000 评论 83199</span>
          <div class="comment-data" id="reply_999_1" ustr="999">
            <div class="comment-data-user"><a class="user-name">第三方</a></div>
            <div class="comment-data-text" id="reply1">不得持久化</div>
          </div>
        </body></html>
        """

        def fetch_html(url: str) -> str:
            return user_topic_html if "moreTopic" in url else article_html

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "main-posts-only.sqlite"
            summary = run_user_topics(
                UserTopicsConfig(
                    db_path=db_path,
                    user_id="1116585",
                    max_pages=1,
                    fetch_article_details=True,
                    max_article_details=1,
                    skip_comments=True,
                    author_comments_only=True,
                    request_interval_seconds=0,
                ),
                fetch_html=fetch_html,
            )
            conn = connect_db(db_path)
            try:
                self.assertEqual(count_rows(conn, "articles"), 1)
                self.assertEqual(count_rows(conn, "comments"), 0)
                self.assertEqual(count_rows(conn, "article_pages"), 1)
            finally:
                conn.close()
            self.assertEqual(summary["comment_pages_mode"], "skipped")
            self.assertEqual(summary["comment_pages_fetched"], 0)
            self.assertEqual(summary["comments_seen"], 0)

    def test_author_archive_fetches_all_comment_pages_but_persists_only_target_id(self):
        # GIVEN：一篇两页评论的目标作者主贴，每页各有作者和第三方回复
        user_topic_html = """
        <html><body>
          <input type="hidden" name="pageNo" value="1"/>
          <script>var pageNum = 1;</script>
          <div class="topic-row">
            <a href="/a/author-post" title="作者主贴">作者主贴</a>
            <a href="/blog/6724235">目标作者</a>
            <span>4 / 100</span><span>08-26 10:00</span>
          </div>
        </body></html>
        """

        def comment(reply_id: str, user_id: str, username: str, text: str) -> str:
            return f"""
            <div class="comment-data" id="reply_{user_id}_{reply_id}" ustr="{user_id}">
              <div class="comment-data-user"><a class="user-name">{username}</a></div>
              <div class="comment-data-text" id="reply{reply_id}">{text}</div>
              <div class="comment-data-button"><span class="left">1楼</span></div>
            </div>
            """

        article_html = f"""
        <html><body>
          <div id="gioMsg" username="目标作者" userid="6724235"></div>
          <h1 id="stockTitle">作者主贴</h1>
          <div id="first">主贴完整正文</div>
          <span>浏览 100 评论 51</span>
          {comment("101", "6724235", "目标作者", "第一页作者回复")}
          {comment("102", "900", "其他人", "第一页第三方回复")}
        </body></html>
        """
        page_two_html = f"""
        <html><body>
          <h1 id="stockTitle">作者主贴</h1>
          {comment("201", "6724235", "目标作者", "第二页作者回复")}
          {comment("202", "901", "另一个人", "第二页第三方回复")}
        </body></html>
        """

        def fetch_html(url: str) -> str:
            if "moreTopic" in url:
                return user_topic_html
            if url.endswith("-2"):
                return page_two_html
            return article_html

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "author-archive.sqlite"
            config = UserTopicsConfig(
                db_path=db_path,
                user_id="6724235",
                max_pages=None,
                fetch_article_details=True,
                max_article_details=None,
                all_comment_pages=True,
                author_comments_only=True,
                request_interval_seconds=0,
            )

            # WHEN：执行通用作者全集模式
            summary = run_user_topics(config, fetch_html=fetch_html)

            # THEN：两页都抓取，但SQLite中没有任何第三方评论详情
            conn = connect_db(db_path)
            try:
                rows = conn.execute(
                    "select reply_id, user_id, is_author from comments order by reply_id"
                ).fetchall()
                self.assertEqual(
                    [(row["reply_id"], row["user_id"], row["is_author"]) for row in rows],
                    [("101", "6724235", 1), ("201", "6724235", 1)],
                )
                self.assertEqual(count_rows(conn, "article_pages"), 2)
            finally:
                conn.close()
            self.assertEqual(summary["article_details_fetched"], 1)
            self.assertEqual(summary["comment_pages_fetched"], 2)
            self.assertEqual(summary["comments_seen"], 4)
            self.assertEqual(summary["comments_excluded_other_users"], 2)
            self.assertEqual(summary["comments_saved"], 2)
            self.assertTrue(summary["author_comments_only"])

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
