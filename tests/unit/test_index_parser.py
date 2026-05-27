from pathlib import Path
import unittest

from common.tgb_index import build_bbs_page_url, parse_bbs_list, parse_bbs_pagination


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

    def test_parse_bbs_pagination_extracts_page_boundaries(self):
        # GIVEN：一份包含论坛分页控件的列表页 HTML fixture
        html = (FIXTURES / "bbs_list_page_1.html").read_text(encoding="utf-8")

        # WHEN：解析分页信息
        pagination = parse_bbs_pagination(html, source_url="https://www.tgb.cn/bbs/1/1")

        # THEN：应得到当前页、总页数、最新页 URL 和最后页 URL
        self.assertEqual(pagination.current_page, 1)
        self.assertGreaterEqual(pagination.total_pages, 90000)
        self.assertEqual(pagination.latest_url, "https://www.tgb.cn/bbs/1/1")
        self.assertEqual(
            pagination.last_url,
            f"https://www.tgb.cn/bbs/{pagination.total_pages}/1",
        )

    def test_build_bbs_page_url(self):
        # GIVEN：论坛页码与分类标记
        page_no = 92757

        # WHEN：构造列表页 URL
        url = build_bbs_page_url(page_no, flag=1)

        # THEN：应得到淘股吧论坛分页 URL
        self.assertEqual(url, "https://www.tgb.cn/bbs/92757/1")


if __name__ == "__main__":
    unittest.main()
