from pathlib import Path
import unittest

from common.tgb_index import parse_bbs_list


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


class TestBbsIndexParser(unittest.TestCase):
    def test_parse_bbs_list_extracts_structured_index_records(self):
        # GIVEN：一份淘股吧论坛列表页 HTML fixture
        html = (FIXTURES / "bbs_list_page_1.html").read_text(encoding="utf-8")

        # WHEN：解析帖子索引
        records = parse_bbs_list(html, source_url="https://www.tgb.cn/bbs/1/1", source_page=1)

        # THEN：应返回包含完整索引字段的帖子记录
        self.assertGreaterEqual(len(records), 50)
        first = records[0]
        self.assertTrue(first.slug)
        self.assertTrue(first.url.startswith("https://www.tgb.cn/a/"))
        self.assertTrue(first.title)
        self.assertTrue(first.author)
        self.assertTrue(first.author_id)
        self.assertIsInstance(first.reply_count, int)
        self.assertIsInstance(first.view_count, int)
        self.assertRegex(first.last_reply_time, r"\d{2}-\d{2} \d{2}:\d{2}")
        self.assertRegex(first.post_time, r"\d{2}-\d{2} \d{2}:\d{2}")
        self.assertEqual(first.source_page, 1)
        self.assertEqual(first.source_url, "https://www.tgb.cn/bbs/1/1")

    def test_parse_bbs_list_preserves_legacy_article_shape(self):
        # GIVEN：一份淘股吧论坛列表页 HTML fixture
        html = (FIXTURES / "bbs_list_page_1.html").read_text(encoding="utf-8")

        # WHEN：解析帖子索引并转换为旧版 article 字典
        first = parse_bbs_list(html, source_url="https://www.tgb.cn/bbs/1/1", source_page=1)[0]
        article = first.to_legacy_article()

        # THEN：应兼容原 `crawler_bbs.crawl_articles()` 的 title/url/href 字段
        self.assertEqual(set(article), {"title", "url", "href"})
        self.assertEqual(article["title"], first.title)
        self.assertEqual(article["url"], first.url)
        self.assertEqual(article["href"], f"a/{first.slug}")


if __name__ == "__main__":
    unittest.main()
