import unittest

from common.tgb_backfill import plan_backfill_pages, plan_comment_pages


class TestBackfillPolicy(unittest.TestCase):
    def test_plan_backfill_pages_scans_from_oldest_backwards(self):
        # GIVEN：论坛总页数和本次 sample 允许抓取的页数
        total_pages = 10

        # WHEN：规划 backfill 页码
        pages = plan_backfill_pages(total_pages=total_pages, max_pages=3)

        # THEN：应从最后页开始倒序抓取
        self.assertEqual(pages, [10, 9, 8])

    def test_plan_backfill_pages_respects_lower_bound(self):
        # GIVEN：总页数很小且请求页数超过边界
        total_pages = 2

        # WHEN：规划 backfill 页码
        pages = plan_backfill_pages(total_pages=total_pages, max_pages=5)

        # THEN：不应出现小于 1 的页码
        self.assertEqual(pages, [2, 1])

    def test_plan_comment_pages_caps_pages_for_sample(self):
        # GIVEN：帖子评论共有 3 页，但 sample 最多只允许抓 2 页
        comment_page_count = 3

        # WHEN：规划评论页
        pages = plan_comment_pages(comment_page_count=comment_page_count, max_pages=2)

        # THEN：只抓前 2 页，避免 sample 变成大规模抓取
        self.assertEqual(pages, [1, 2])


if __name__ == "__main__":
    unittest.main()
