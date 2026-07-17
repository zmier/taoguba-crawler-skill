import unittest
import tempfile
from pathlib import Path

from common.tgb_user_topics import (
    build_user_topic_page_url,
    enqueue_missing_article_details,
    parse_user_topic_pagination,
    plan_user_topic_pages,
)
from common.tgb_index import BbsIndexRecord
from common.tgb_storage import connect_db, init_db, upsert_article_detail, upsert_index_records
from common.tgb_article import ArticleDetail


class TestUserTopicsPolicy(unittest.TestCase):
    def test_build_user_topic_page_url(self):
        # GIVEN：淘股吧用户 ID 和页码
        user_id = "252069"

        # WHEN：构造用户最新主帖分页 URL
        url = build_user_topic_page_url(user_id, page_no=2)

        # THEN：应得到 moreTopic 分页地址
        self.assertEqual(url, "https://www.tgb.cn/user/blog/moreTopic?userID=252069&pageNo=2")

    def test_parse_user_topic_pagination_from_page_script(self):
        # GIVEN：用户主帖页中的分页脚本和隐藏表单
        html = """
        <form name="nameFrm">
          <input type="hidden" name="userID" value="252069"/>
          <input type="hidden" name="pageNo" value="1"/>
        </form>
        <script>
        function gotoPage(pageNo){
          var pageNum = 37;
        }
        </script>
        """

        # WHEN：解析用户主帖分页
        pagination = parse_user_topic_pagination(
            html,
            source_url="https://www.tgb.cn/user/blog/moreTopic?userID=252069&pageNo=1",
        )

        # THEN：应得到当前页、总页数和末页 URL
        self.assertEqual(pagination.user_id, "252069")
        self.assertEqual(pagination.current_page, 1)
        self.assertEqual(pagination.total_pages, 37)
        self.assertEqual(
            pagination.last_url,
            "https://www.tgb.cn/user/blog/moreTopic?userID=252069&pageNo=37",
        )

    def test_plan_user_topic_pages_honors_limits(self):
        # GIVEN：全集 37 页，但本次只想从第 2 页抓 3 页
        total_pages = 37

        # WHEN：规划抓取页码
        pages = plan_user_topic_pages(total_pages, start_page=2, max_pages=3)

        # THEN：应顺序抓取 2、3、4 页
        self.assertEqual(pages, [2, 3, 4])

    def test_enqueue_missing_article_details_uses_existing_index(self):
        # GIVEN：数据库中已有两个用户主帖索引，其中一个已经抓过详情
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "user-topic.sqlite"
            conn = connect_db(db_path)
            init_db(conn)
            records = [
                BbsIndexRecord(
                    slug="new-one",
                    url="https://www.tgb.cn/a/new-one",
                    title="新帖",
                    author="柏拉爱空",
                    author_id="252069",
                    reply_count=1,
                    view_count=10,
                    last_reply_time="07-16 10:00",
                    post_time="07-16 09:00",
                    source_page=1,
                    source_url="https://www.tgb.cn/user/blog/moreTopic?userID=252069&pageNo=1",
                ),
                BbsIndexRecord(
                    slug="done-one",
                    url="https://www.tgb.cn/a/done-one",
                    title="已抓详情",
                    author="柏拉爱空",
                    author_id="252069",
                    reply_count=1,
                    view_count=10,
                    last_reply_time="07-15 10:00",
                    post_time="07-15 09:00",
                    source_page=1,
                    source_url="https://www.tgb.cn/user/blog/moreTopic?userID=252069&pageNo=1",
                ),
            ]
            upsert_index_records(conn, records)
            upsert_article_detail(
                conn,
                ArticleDetail(
                    slug="done-one",
                    url="https://www.tgb.cn/a/done-one",
                    topic_id="1",
                    title="已抓详情",
                    author="柏拉爱空",
                    author_id="252069",
                    view_count=10,
                    comment_count=0,
                    comment_page_count=1,
                    main_text="done",
                    main_html="<div>done</div>",
                    image_urls=[],
                ),
            )

            # WHEN：从已有索引入队缺失详情
            enqueued = enqueue_missing_article_details(conn, "252069")

            # THEN：只入队未抓详情的帖子
            self.assertEqual(enqueued, 1)
            pending = conn.execute(
                "select url from crawl_queue where kind = 'article' and status = 'pending'"
            ).fetchall()
            self.assertEqual([row["url"] for row in pending], ["https://www.tgb.cn/a/new-one"])
            conn.close()


if __name__ == "__main__":
    unittest.main()
