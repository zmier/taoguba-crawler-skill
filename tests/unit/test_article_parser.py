from pathlib import Path
import unittest

from common.tgb_article import parse_article_detail


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


class TestArticleParser(unittest.TestCase):
    def test_parse_article_detail_extracts_main_post_fields(self):
        # GIVEN：一份包含主帖、作者信息、浏览评论计数的帖子详情 HTML
        html = (FIXTURES / "article_detail_2s8aVDvYC5w.html").read_text(encoding="utf-8")

        # WHEN：解析帖子详情页
        article = parse_article_detail(html, url="https://www.tgb.cn/a/2s8aVDvYC5w")

        # THEN：应返回主帖结构化字段
        self.assertEqual(article.slug, "2s8aVDvYC5w")
        self.assertEqual(article.topic_id, "8382947")
        self.assertEqual(article.title, "指数这样的图形，怕不怕周四的剧本？")
        self.assertEqual(article.author, "朱雀路作手")
        self.assertEqual(article.author_id, "7105646")
        self.assertGreaterEqual(article.view_count, 1)
        self.assertGreaterEqual(article.comment_count, 1)
        self.assertGreaterEqual(article.comment_page_count, 1)
        self.assertIn("每日思路验证情况解析", article.main_text)
        self.assertIn('id="first"', article.main_html)
        self.assertGreaterEqual(len(article.image_urls), 1)
        self.assertTrue(article.image_urls[0].startswith("https://image.tgb.cn/"))


if __name__ == "__main__":
    unittest.main()
