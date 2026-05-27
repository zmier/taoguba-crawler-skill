from pathlib import Path
import tempfile
import unittest

from common.tgb_sample import SampleConfig, run_sample


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


class TestSampleAcceptance(unittest.TestCase):
    def test_sample_summary_is_user_acceptance_ready(self):
        # GIVEN：一个限制为 1 页列表、1 篇详情、1 页评论的 sample 配置
        list_html = (FIXTURES / "bbs_list_page_1.html").read_text(encoding="utf-8")
        article_html = (FIXTURES / "article_detail_2s8aVDvYC5w.html").read_text(encoding="utf-8")

        def fetch_html(url: str) -> str:
            return list_html if "/bbs/" in url else article_html

        with tempfile.TemporaryDirectory() as tmpdir:
            config = SampleConfig(
                db_path=Path(tmpdir) / "sample.sqlite",
                list_urls=["https://www.tgb.cn/bbs/1/1"],
                max_articles=1,
                comment_pages_per_article=1,
                request_interval_seconds=0,
            )

            # WHEN：运行 sample
            summary = run_sample(config, fetch_html=fetch_html)

            # THEN：验收摘要应清楚表明这不是 full 全量运行，并给出关键计数
            self.assertEqual(summary["mode"], "sample")
            self.assertFalse(summary["full_run"])
            self.assertEqual(summary["list_pages_fetched"], 1)
            self.assertEqual(summary["article_details_fetched"], 1)
            self.assertGreaterEqual(summary["index_records_saved"], 50)
            self.assertEqual(summary["comment_pages_fetched"], 1)
            self.assertEqual(summary["comments_saved"], 50)
            self.assertEqual(summary["failures"], 0)


if __name__ == "__main__":
    unittest.main()
