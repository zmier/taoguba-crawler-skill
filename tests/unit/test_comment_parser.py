from pathlib import Path
import unittest

from common.tgb_comment import build_comment_page_url, parse_comments


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


class TestCommentParser(unittest.TestCase):
    def test_parse_comments_extracts_all_comment_blocks(self):
        # GIVEN：一份包含评论区的帖子详情 HTML
        html = (FIXTURES / "article_detail_2s8aVDvYC5w.html").read_text(encoding="utf-8")

        # WHEN：解析评论列表
        comments = parse_comments(html, article_slug="2s8aVDvYC5w", page_no=1)

        # THEN：应返回当前页所有评论的结构化数据
        self.assertEqual(len(comments), 50)
        first = comments[0]
        self.assertEqual(first.article_slug, "2s8aVDvYC5w")
        self.assertEqual(first.reply_id, "99129433")
        self.assertEqual(first.user_id, "14082885")
        self.assertEqual(first.username, "王先生的小弟弟")
        self.assertEqual(first.floor_label, "沙发")
        self.assertEqual(first.created_at, "2026-05-27 08:00")
        self.assertEqual(first.text, "第一个")
        self.assertFalse(first.is_author)
        self.assertEqual(first.page_no, 1)

    def test_parse_comments_identifies_author_replies(self):
        # GIVEN：一份包含楼主回复的帖子详情 HTML
        html = (FIXTURES / "article_detail_2s8aVDvYC5w.html").read_text(encoding="utf-8")

        # WHEN：解析评论列表
        comments = parse_comments(html, article_slug="2s8aVDvYC5w", page_no=1)
        author_comments = [item for item in comments if item.is_author]

        # THEN：应识别楼主评论
        self.assertGreaterEqual(len(author_comments), 1)
        self.assertEqual(author_comments[0].username, "朱雀路作手")
        self.assertEqual(author_comments[0].user_id, "7105646")

    def test_build_comment_page_url(self):
        # GIVEN：帖子 slug 与评论页码
        slug = "2s8aVDvYC5w"

        # WHEN：构造评论分页 URL
        first_page = build_comment_page_url(slug, 1)
        second_page = build_comment_page_url(slug, 2)

        # THEN：第一页使用主贴 URL，后续页追加 -page
        self.assertEqual(first_page, "https://www.tgb.cn/a/2s8aVDvYC5w")
        self.assertEqual(second_page, "https://www.tgb.cn/a/2s8aVDvYC5w-2")


if __name__ == "__main__":
    unittest.main()
