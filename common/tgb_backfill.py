from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time
from typing import Callable

from common.tgb_article import parse_article_detail
from common.tgb_comment import build_comment_page_url, parse_comments
from common.tgb_index import build_bbs_page_url, parse_bbs_list
from common.tgb_resume import enqueue, mark_done, mark_failed
from common.tgb_storage import (
    connect_db,
    count_rows,
    init_db,
    upsert_article_detail,
    upsert_article_page,
    upsert_comments,
    upsert_index_records,
)


FetchHtml = Callable[[str], str]


@dataclass(frozen=True)
class BackfillSampleConfig:
    db_path: Path
    total_pages: int
    flag: int = 1
    max_list_pages: int = 2
    max_articles_per_page: int = 3
    max_comment_pages_per_article: int = 2
    request_interval_seconds: float = 1.0
    max_attempts: int = 2
    backoff_seconds: int = 60


def plan_backfill_pages(total_pages: int, max_pages: int) -> list[int]:
    if total_pages < 1 or max_pages < 1:
        return []
    stop = max(0, total_pages - max_pages)
    return list(range(total_pages, stop, -1))


def plan_comment_pages(comment_page_count: int, max_pages: int) -> list[int]:
    if max_pages < 1:
        return []
    total = max(1, comment_page_count)
    return list(range(1, min(total, max_pages) + 1))


def run_backfill_sample(config: BackfillSampleConfig, fetch_html: FetchHtml) -> dict[str, object]:
    conn = connect_db(config.db_path)
    init_db(conn)
    summary: dict[str, object] = {
        "mode": "backfill_sample",
        "full_run": False,
        "full_run_gate": "manual_approval_required",
        "direction": "reverse",
        "db_path": str(config.db_path),
        "total_pages": config.total_pages,
        "list_pages_planned": plan_backfill_pages(config.total_pages, config.max_list_pages),
        "list_pages_scanned": 0,
        "index_records_seen": 0,
        "article_details_fetched": 0,
        "comment_pages_fetched": 0,
        "comments_saved": 0,
        "queue_done": 0,
        "failures": 0,
        "stop_reason": "",
    }

    try:
        for page_no in summary["list_pages_planned"]:
            page_url = build_bbs_page_url(int(page_no), config.flag)
            html = fetch_html(page_url)
            records = parse_bbs_list(html, source_url=page_url, source_page=int(page_no))
            upsert_index_records(conn, records)
            selected = records[-config.max_articles_per_page :] if config.max_articles_per_page else []
            for record in selected:
                enqueue(conn, record.url, kind="article", priority=int(page_no))
                _fetch_article_and_comments(conn, config, fetch_html, record.url, summary)
            summary["list_pages_scanned"] = int(summary["list_pages_scanned"]) + 1
            summary["index_records_seen"] = int(summary["index_records_seen"]) + len(records)
            _sleep(config.request_interval_seconds)

        summary["queue_done"] = conn.execute(
            "select count(*) from crawl_queue where status = 'done'"
        ).fetchone()[0]
        summary["failures"] = count_rows(conn, "failures")
        summary["stop_reason"] = "sample_limits_reached"
        return summary
    finally:
        conn.close()


def _fetch_article_and_comments(
    conn,
    config: BackfillSampleConfig,
    fetch_html: FetchHtml,
    url: str,
    summary: dict[str, object],
) -> None:
    try:
        html = fetch_html(url)
        detail = parse_article_detail(html, url=url)
        if not detail.slug:
            raise ValueError(f"无法从 URL 解析帖子 slug: {url}")
        upsert_article_detail(conn, detail)
        summary["article_details_fetched"] = int(summary["article_details_fetched"]) + 1

        for page_no in plan_comment_pages(detail.comment_page_count, config.max_comment_pages_per_article):
            comment_url = url if page_no == 1 else build_comment_page_url(detail.slug, page_no)
            comment_html = html if page_no == 1 else fetch_html(comment_url)
            comments = parse_comments(comment_html, article_slug=detail.slug, page_no=page_no)
            upsert_comments(conn, comments)
            upsert_article_page(conn, detail.slug, page_no, comment_url, comment_html)
            summary["comment_pages_fetched"] = int(summary["comment_pages_fetched"]) + 1
            summary["comments_saved"] = int(summary["comments_saved"]) + len(comments)
            _sleep(config.request_interval_seconds)
        mark_done(conn, url)
    except Exception as exc:
        mark_failed(
            conn,
            url,
            error=str(exc),
            max_attempts=config.max_attempts,
            backoff_seconds=config.backoff_seconds,
        )


def _sleep(seconds: float) -> None:
    if seconds > 0:
        time.sleep(seconds)
