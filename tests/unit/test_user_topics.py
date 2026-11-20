import unittest
import tempfile
from pathlib import Path

from common.tgb_user_topics import (
    AuthorArchiveAuthenticationError,
    build_user_topic_page_url,
    enqueue_author_archive_gaps,
    enqueue_missing_article_details,
    parse_user_topic_pagination,
    plan_user_topic_pages,
    select_comments_for_storage,
    validate_author_archive_detail,
)
from common.tgb_comment import CommentRecord
from common.tgb_index import BbsIndexRecord
from common.tgb_storage import (
    connect_db,
    init_db,
    upsert_article_detail,
    upsert_article_page,
    upsert_index_records,
)
from common.tgb_article import ArticleDetail
from common.tgb_resume import enqueue, mark_done


class TestUserTopicsPolicy(unittest.TestCase):
    def test_image_only_diary_is_valid_and_stays_complete_on_resume(self):
        from common.tgb_article import parse_article_detail

        image = "https://image.tgb.cn/img/2023/12/19/example.jpg"
        html = (f'<div id="first"><img data-original="{image}"></div>'
                '<div id="gioMsg" userid="777" username="作者"></div>'
                '<div id="stockTitle">当日实盘</div>')
        detail = parse_article_detail(html, url="https://www.tgb.cn/a/diary")
        validate_author_archive_detail(detail, html=html, expected_user_id="777")
        self.assertEqual(detail.main_text, "")
        self.assertEqual(detail.image_urls, [image])
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = connect_db(Path(tmpdir) / "diary.sqlite")
            init_db(conn)
            upsert_article_detail(conn, detail)
            upsert_article_page(conn, detail.slug, 1, detail.url, html)
            self.assertEqual(enqueue_missing_article_details(conn, "777"), 0)
            self.assertEqual(enqueue_author_archive_gaps(conn, "777"), 0)
            conn.close()

    def test_author_archive_requeues_an_old_partial_comment_capture(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "partial.sqlite"
            conn = connect_db(db_path)
            init_db(conn)
            detail = ArticleDetail(
                slug="post-one",
                url="https://www.tgb.cn/a/post-one",
                topic_id="1",
                title="主贴",
                author="作者",
                author_id="777",
                view_count=1,
                comment_count=120,
                comment_page_count=3,
                main_text="完整正文",
                main_html="<div>完整正文</div>",
                image_urls=[],
            )
            upsert_article_detail(conn, detail)
            upsert_article_page(conn, detail.slug, 1, detail.url, "<html>page1</html>")
            enqueue(conn, detail.url, kind="article")
            mark_done(conn, detail.url)

            enqueued = enqueue_author_archive_gaps(conn, "777")

            self.assertEqual(enqueued, 1)
            self.assertEqual(
                conn.execute(
                    "select status from crawl_queue where url = ?",
                    (detail.url,),
                ).fetchone()["status"],
                "pending",
            )
            conn.close()

    def test_author_archive_requeues_a_legacy_done_detail_with_empty_body(self):
        # GIVEN：旧任务把空正文详情错误标成 fetched/done
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "legacy-empty.sqlite"
            conn = connect_db(db_path)
            init_db(conn)
            detail = ArticleDetail(
                slug="empty-one",
                url="https://www.tgb.cn/a/empty-one",
                topic_id="1",
                title="旧主贴",
                author="目标作者",
                author_id="777",
                view_count=1,
                comment_count=0,
                comment_page_count=1,
                main_text="",
                main_html="",
                image_urls=[],
            )
            upsert_article_detail(conn, detail)
            enqueue(conn, detail.url, kind="article")
            mark_done(conn, detail.url)

            # WHEN：按 author-only archive 契约扫描缺口
            enqueued = enqueue_author_archive_gaps(conn, "777")

            # THEN：空正文即使已有 fetched/done 也必须重新排队
            self.assertEqual(enqueued, 1)
            self.assertEqual(
                conn.execute(
                    "select status from crawl_queue where url = ?",
                    (detail.url,),
                ).fetchone()["status"],
                "pending",
            )
            conn.close()

    def test_author_archive_fails_closed_on_wrong_detail_author(self):
        detail = ArticleDetail(
            slug="post-one",
            url="https://www.tgb.cn/a/post-one",
            topic_id="1",
            title="主贴",
            author="别的作者",
            author_id="888",
            view_count=1,
            comment_count=0,
            comment_page_count=1,
            main_text="正文",
            main_html="<div>正文</div>",
            image_urls=[],
        )
        with self.assertRaises(AuthorArchiveAuthenticationError):
            validate_author_archive_detail(
                detail,
                html="<html>正文</html>",
                expected_user_id="777",
            )

    def test_author_only_storage_filters_by_immutable_user_id(self):
        # GIVEN：UI“楼主”标记有一正一反两个错位，另有第三方回复
        comments = [
            CommentRecord(
                article_slug="post-one",
                page_no=1,
                reply_id="a1",
                user_id="6724235",
                username="作者",
                is_author=False,
                floor_label="1楼",
                created_at="2026-08-26 10:00",
                text="作者回复",
                html="<div>作者回复</div>",
                image_urls=[],
            ),
            CommentRecord(
                article_slug="post-one",
                page_no=1,
                reply_id="b1",
                user_id="100",
                username="其他人",
                is_author=True,
                floor_label="2楼",
                created_at="2026-08-26 10:01",
                text="第三方回复",
                html="<div>第三方回复</div>",
                image_urls=[],
            ),
        ]

        # WHEN：按不可变ID选择作者回复
        selected = select_comments_for_storage(
            comments,
            target_user_id="6724235",
            author_comments_only=True,
        )

        # THEN：只保留目标ID，并规范化作者标记
        self.assertEqual([row.reply_id for row in selected], ["a1"])
        self.assertTrue(selected[0].is_author)

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

    def test_enqueue_missing_article_details_requeues_legacy_done_empty_body(self):
        # GIVEN：索引详情已有 fetched_at，但正文为空且 queue 错误为 done
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "legacy-empty.sqlite"
            conn = connect_db(db_path)
            init_db(conn)
            detail = ArticleDetail(
                slug="empty-one",
                url="https://www.tgb.cn/a/empty-one",
                topic_id="1",
                title="旧主贴",
                author="柏拉爱空",
                author_id="252069",
                view_count=1,
                comment_count=0,
                comment_page_count=1,
                main_text="",
                main_html="",
                image_urls=[],
            )
            upsert_article_detail(conn, detail)
            enqueue(conn, detail.url, kind="article")
            mark_done(conn, detail.url)

            # WHEN：普通 details-only 扫描缺失详情
            enqueued = enqueue_missing_article_details(conn, "252069")

            # THEN：不能让旧 fetched/done 掩盖空正文
            self.assertEqual(enqueued, 1)
            self.assertEqual(
                conn.execute(
                    "select status from crawl_queue where url = ?",
                    (detail.url,),
                ).fetchone()["status"],
                "pending",
            )
            conn.close()

    def test_enqueue_missing_article_details_keeps_terminal_wrong_author_gap_failed(self):
        # GIVEN：旧索引短链已碰撞到另一作者，且已明确进入 terminal failure
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "wrong-author.sqlite"
            conn = connect_db(db_path)
            init_db(conn)
            detail = ArticleDetail(
                slug="collided-one",
                url="https://www.tgb.cn/a/collided-one",
                topic_id="",
                title="旧索引标题",
                author="目标作者",
                author_id="777",
                view_count=1,
                comment_count=0,
                comment_page_count=1,
                main_text="",
                main_html="",
                image_urls=[],
            )
            upsert_article_detail(conn, detail)
            enqueue(conn, detail.url, kind="article")
            conn.execute(
                """
                update crawl_queue
                set status='failed', attempts=3,
                    last_error='author_detail_user_id_mismatch:888!=777'
                where url=?
                """,
                (detail.url,),
            )
            conn.commit()

            # WHEN：下一次 details-only 扫描空正文
            enqueued = enqueue_missing_article_details(conn, "777")

            # THEN：保留显式 source gap，不重排也不写入异作者正文
            row = conn.execute(
                "select status, last_error from crawl_queue where url=?",
                (detail.url,),
            ).fetchone()
            self.assertEqual(enqueued, 0)
            self.assertEqual(row["status"], "failed")
            self.assertTrue(row["last_error"].startswith("author_detail_user_id_mismatch:"))
            conn.close()


if __name__ == "__main__":
    unittest.main()
