import tempfile
import unittest

from common.tgb_resume import (
    claim_next,
    enqueue,
    get_queue_item,
    mark_done,
    mark_failed,
    reset_stale_running,
)
from common.tgb_storage import connect_db, count_rows, init_db


class TestResumeQueue(unittest.TestCase):
    def test_enqueue_is_idempotent(self):
        # GIVEN：一个已初始化的爬取队列表
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = connect_db(f"{tmpdir}/tgb.sqlite")
            init_db(conn)

            # WHEN：重复入队同一个 URL
            enqueue(conn, "https://www.tgb.cn/a/abc123", kind="article", priority=10)
            enqueue(conn, "https://www.tgb.cn/a/abc123", kind="article", priority=10)

            # THEN：队列表只保留一条 pending 任务
            self.assertEqual(count_rows(conn, "crawl_queue"), 1)
            item = get_queue_item(conn, "https://www.tgb.cn/a/abc123")
            self.assertEqual(item["status"], "pending")
            self.assertEqual(item["priority"], 10)

    def test_claim_next_marks_task_running(self):
        # GIVEN：两个不同优先级的待抓取任务
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = connect_db(f"{tmpdir}/tgb.sqlite")
            init_db(conn)
            enqueue(conn, "https://www.tgb.cn/a/low", kind="article", priority=1)
            enqueue(conn, "https://www.tgb.cn/a/high", kind="article", priority=9)

            # WHEN：领取下一条 article 任务
            task = claim_next(conn, kind="article", now="2026-05-27T12:00:00+00:00")

            # THEN：应领取高优先级任务，并将其标记为 running
            self.assertEqual(task["url"], "https://www.tgb.cn/a/high")
            stored = get_queue_item(conn, "https://www.tgb.cn/a/high")
            self.assertEqual(stored["status"], "running")

    def test_mark_done_finishes_running_task(self):
        # GIVEN：一条已领取的任务
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = connect_db(f"{tmpdir}/tgb.sqlite")
            init_db(conn)
            enqueue(conn, "https://www.tgb.cn/a/abc123", kind="article")
            claim_next(conn, kind="article", now="2026-05-27T12:00:00+00:00")

            # WHEN：标记任务完成
            mark_done(conn, "https://www.tgb.cn/a/abc123", now="2026-05-27T12:01:00+00:00")

            # THEN：任务状态应变成 done
            item = get_queue_item(conn, "https://www.tgb.cn/a/abc123")
            self.assertEqual(item["status"], "done")
            self.assertEqual(item["last_error"], "")

    def test_mark_failed_retries_then_marks_failed(self):
        # GIVEN：一条运行中任务，最多允许两次失败
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = connect_db(f"{tmpdir}/tgb.sqlite")
            init_db(conn)
            url = "https://www.tgb.cn/a/abc123"
            enqueue(conn, url, kind="article")
            claim_next(conn, kind="article", now="2026-05-27T12:00:00+00:00")

            # WHEN：第一次失败
            mark_failed(
                conn,
                url,
                error="timeout",
                max_attempts=2,
                backoff_seconds=30,
                now="2026-05-27T12:00:00+00:00",
            )

            # THEN：任务回到 pending，并带有下一次运行时间
            item = get_queue_item(conn, url)
            self.assertEqual(item["status"], "pending")
            self.assertEqual(item["attempts"], 1)
            self.assertEqual(item["next_run_at"], "2026-05-27T12:00:30+00:00")

            # WHEN：再次领取并失败
            claim_next(conn, kind="article", now="2026-05-27T12:00:30+00:00")
            mark_failed(
                conn,
                url,
                error="still timeout",
                max_attempts=2,
                backoff_seconds=30,
                now="2026-05-27T12:00:30+00:00",
            )

            # THEN：任务达到上限后转为 failed，并写入失败历史
            item = get_queue_item(conn, url)
            self.assertEqual(item["status"], "failed")
            self.assertEqual(item["attempts"], 2)
            self.assertEqual(count_rows(conn, "failures"), 2)

    def test_reset_stale_running_moves_old_tasks_back_to_pending(self):
        # GIVEN：一条长时间卡在 running 的任务
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = connect_db(f"{tmpdir}/tgb.sqlite")
            init_db(conn)
            url = "https://www.tgb.cn/a/abc123"
            enqueue(conn, url, kind="article")
            claim_next(conn, kind="article", now="2026-05-27T12:00:00+00:00")

            # WHEN：超过阈值后重置 running 任务
            reset_count = reset_stale_running(
                conn,
                older_than_seconds=60,
                now="2026-05-27T12:02:01+00:00",
            )

            # THEN：任务应回到 pending，供下次恢复继续抓
            self.assertEqual(reset_count, 1)
            item = get_queue_item(conn, url)
            self.assertEqual(item["status"], "pending")


if __name__ == "__main__":
    unittest.main()
