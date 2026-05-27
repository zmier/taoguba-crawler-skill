import tempfile
import unittest

from common.tgb_incremental import (
    IncrementalScanState,
    StopPolicy,
    find_comment_refresh_candidates,
    should_stop_incremental,
)
from common.tgb_index import BbsIndexRecord
from common.tgb_storage import connect_db, init_db, upsert_index_records


class TestIncrementalPolicy(unittest.TestCase):
    def test_should_stop_after_consecutive_known_articles(self):
        # GIVEN：连续已知帖子数达到阈值
        state = IncrementalScanState(
            pages_scanned=1,
            consecutive_known_articles=50,
            consecutive_no_new_pages=0,
        )
        policy = StopPolicy(max_pages=5, known_article_threshold=50, no_new_page_threshold=2)

        # WHEN：判断是否停止增量扫描
        decision = should_stop_incremental(state, policy)

        # THEN：应停止并返回 known_articles 阈值原因
        self.assertTrue(decision.stop)
        self.assertEqual(decision.reason, "known_article_threshold")

    def test_should_stop_after_no_new_pages(self):
        # GIVEN：连续无新增页数达到阈值
        state = IncrementalScanState(
            pages_scanned=2,
            consecutive_known_articles=0,
            consecutive_no_new_pages=2,
        )
        policy = StopPolicy(max_pages=5, known_article_threshold=50, no_new_page_threshold=2)

        # WHEN：判断是否停止增量扫描
        decision = should_stop_incremental(state, policy)

        # THEN：应停止并返回 no_new_pages 阈值原因
        self.assertTrue(decision.stop)
        self.assertEqual(decision.reason, "no_new_page_threshold")

    def test_find_comment_refresh_candidates_prefers_reply_count_gap(self):
        # GIVEN：一个已入库帖子，其列表回复数大于已存评论数
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = connect_db(f"{tmpdir}/tgb.sqlite")
            init_db(conn)
            upsert_index_records(
                conn,
                [
                    BbsIndexRecord(
                        slug="abc123",
                        url="https://www.tgb.cn/a/abc123",
                        title="有评论变化的帖子",
                        author="作者",
                        author_id="1",
                        reply_count=2,
                        view_count=10,
                        last_reply_time="05-27 10:00",
                        post_time="05-27 09:00",
                        source_page=1,
                        source_url="https://www.tgb.cn/bbs/1/1",
                    )
                ],
            )
            conn.execute(
                "update articles set fetched_at = ?, updated_at = ? where slug = ?",
                ("2026-05-27T00:00:00+00:00", "2026-05-27T00:00:00+00:00", "abc123"),
            )
            conn.commit()

            # WHEN：查找评论复查候选
            candidates = find_comment_refresh_candidates(conn, limit=10)

            # THEN：应选出 reply_count 大于 comments_count 的帖子
            self.assertEqual(len(candidates), 1)
            self.assertEqual(candidates[0]["slug"], "abc123")
            self.assertEqual(candidates[0]["missing_comments"], 2)
            conn.close()


if __name__ == "__main__":
    unittest.main()
