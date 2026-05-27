import tempfile
import unittest

from common.tgb_article import ArticleDetail
from common.tgb_comment import CommentRecord
from common.tgb_index import BbsIndexRecord
from common.tgb_storage import (
    connect_db,
    count_rows,
    get_article,
    init_db,
    upsert_article_detail,
    upsert_comments,
    upsert_index_records,
)


class TestTgbStorage(unittest.TestCase):
    def test_init_db_creates_required_tables(self):
        # GIVEN：一个空的临时 SQLite 数据库
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = connect_db(f"{tmpdir}/tgb.sqlite")

            # WHEN：初始化 schema
            init_db(conn)

            # THEN：应创建全量爬取需要的核心表
            table_names = {
                row["name"]
                for row in conn.execute(
                    "select name from sqlite_master where type = 'table'"
                ).fetchall()
            }
            self.assertIn("articles", table_names)
            self.assertIn("article_pages", table_names)
            self.assertIn("comments", table_names)
            self.assertIn("crawl_queue", table_names)
            self.assertIn("failures", table_names)

    def test_upsert_index_records_is_idempotent(self):
        # GIVEN：一条帖子列表索引记录
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = connect_db(f"{tmpdir}/tgb.sqlite")
            init_db(conn)
            record = BbsIndexRecord(
                slug="abc123",
                url="https://www.tgb.cn/a/abc123",
                title="测试标题",
                author="作者",
                author_id="42",
                reply_count=3,
                view_count=99,
                last_reply_time="05-27 12:00",
                post_time="05-27 10:00",
                source_page=1,
                source_url="https://www.tgb.cn/bbs/1/1",
            )

            # WHEN：重复写入同一条索引记录
            upsert_index_records(conn, [record])
            upsert_index_records(conn, [record])

            # THEN：articles 表应只保留一行，并保留索引字段
            self.assertEqual(count_rows(conn, "articles"), 1)
            article = get_article(conn, "abc123")
            self.assertEqual(article["title"], "测试标题")
            self.assertEqual(article["reply_count"], 3)
            self.assertEqual(article["source_page"], 1)

    def test_upsert_article_detail_enriches_existing_article(self):
        # GIVEN：一条已由列表页发现的帖子和对应详情记录
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = connect_db(f"{tmpdir}/tgb.sqlite")
            init_db(conn)
            upsert_index_records(
                conn,
                [
                    BbsIndexRecord(
                        slug="abc123",
                        url="https://www.tgb.cn/a/abc123",
                        title="旧标题",
                        author="旧作者",
                        author_id="42",
                        reply_count=0,
                        view_count=0,
                        last_reply_time="",
                        post_time="",
                        source_page=1,
                        source_url="https://www.tgb.cn/bbs/1/1",
                    )
                ],
            )
            detail = ArticleDetail(
                slug="abc123",
                url="https://www.tgb.cn/a/abc123",
                topic_id="1001",
                title="详情标题",
                author="详情作者",
                author_id="43",
                view_count=120,
                comment_count=8,
                comment_page_count=1,
                main_text="正文",
                main_html="<div>正文</div>",
                image_urls=["https://image.tgb.cn/a.png"],
            )

            # WHEN：写入详情记录
            upsert_article_detail(conn, detail)

            # THEN：同一 slug 应被补充详情字段，而不是新增重复帖子
            self.assertEqual(count_rows(conn, "articles"), 1)
            article = get_article(conn, "abc123")
            self.assertEqual(article["title"], "详情标题")
            self.assertEqual(article["topic_id"], "1001")
            self.assertEqual(article["comment_count"], 8)
            self.assertEqual(article["image_urls_json"], '["https://image.tgb.cn/a.png"]')

    def test_upsert_comments_is_idempotent(self):
        # GIVEN：两条属于同一帖子的评论记录
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = connect_db(f"{tmpdir}/tgb.sqlite")
            init_db(conn)
            comments = [
                CommentRecord(
                    article_slug="abc123",
                    page_no=1,
                    reply_id="r1",
                    user_id="u1",
                    username="用户1",
                    is_author=False,
                    floor_label="沙发",
                    created_at="2026-05-27 12:00",
                    text="评论1",
                    html="<div>评论1</div>",
                    image_urls=[],
                ),
                CommentRecord(
                    article_slug="abc123",
                    page_no=1,
                    reply_id="r2",
                    user_id="u2",
                    username="用户2",
                    is_author=True,
                    floor_label="板凳",
                    created_at="2026-05-27 12:01",
                    text="评论2",
                    html="<div>评论2</div>",
                    image_urls=["https://image.tgb.cn/b.png"],
                ),
            ]

            # WHEN：重复写入同一批评论
            upsert_comments(conn, comments)
            upsert_comments(conn, comments)

            # THEN：comments 表应按 article_slug + reply_id 去重
            self.assertEqual(count_rows(conn, "comments"), 2)
            row = conn.execute(
                "select * from comments where article_slug = ? and reply_id = ?",
                ("abc123", "r2"),
            ).fetchone()
            self.assertEqual(row["username"], "用户2")
            self.assertEqual(row["is_author"], 1)
            self.assertEqual(row["image_urls_json"], '["https://image.tgb.cn/b.png"]')


if __name__ == "__main__":
    unittest.main()
