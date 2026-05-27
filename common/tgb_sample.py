from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time
from typing import Callable

from common.tgb_article import parse_article_detail
from common.tgb_comment import build_comment_page_url, parse_comments
from common.tgb_index import parse_bbs_list
from common.tgb_resume import claim_next, enqueue, mark_done, mark_failed
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
class SampleConfig:
    db_path: Path
    list_urls: list[str]
    max_articles: int = 3
    comment_pages_per_article: int = 1
    request_interval_seconds: float = 0.5
    max_attempts: int = 3
    backoff_seconds: int = 30


def run_sample(config: SampleConfig, fetch_html: FetchHtml) -> dict[str, object]:
    conn = connect_db(config.db_path)
    init_db(conn)

    summary: dict[str, object] = {
        "mode": "sample",
        "full_run": False,
        "db_path": str(config.db_path),
        "list_pages_fetched": 0,
        "index_records_saved": 0,
        "article_details_fetched": 0,
        "comment_pages_fetched": 0,
        "comments_saved": 0,
        "failures": 0,
    }

    try:
        for list_url in config.list_urls:
            html = fetch_html(list_url)
            source_page = _source_page_from_url(list_url)
            records = parse_bbs_list(html, source_url=list_url, source_page=source_page)
            upsert_index_records(conn, records)
            for record in records:
                enqueue(conn, record.url, kind="article", priority=max(0, 1000 - record.source_page))
            summary["list_pages_fetched"] = int(summary["list_pages_fetched"]) + 1
            summary["index_records_saved"] = int(summary["index_records_saved"]) + len(records)
            _sleep(config.request_interval_seconds)

        for _ in range(config.max_articles):
            task = claim_next(conn, kind="article")
            if task is None:
                break
            url = task["url"]
            try:
                html = fetch_html(url)
                detail = parse_article_detail(html, url=url)
                if not detail.slug:
                    raise ValueError(f"无法从 URL 解析帖子 slug: {url}")

                upsert_article_detail(conn, detail)
                upsert_article_page(conn, detail.slug, 1, url, html)
                summary["article_details_fetched"] = int(summary["article_details_fetched"]) + 1

                first_page_comments = parse_comments(html, article_slug=detail.slug, page_no=1)
                upsert_comments(conn, first_page_comments)
                summary["comment_pages_fetched"] = int(summary["comment_pages_fetched"]) + 1
                summary["comments_saved"] = int(summary["comments_saved"]) + len(first_page_comments)

                for page_no in range(2, config.comment_pages_per_article + 1):
                    comment_url = build_comment_page_url(detail.slug, page_no)
                    comment_html = fetch_html(comment_url)
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
            _sleep(config.request_interval_seconds)

        summary["failures"] = count_rows(conn, "failures")
        return summary
    finally:
        conn.close()


def _source_page_from_url(url: str) -> int:
    parts = [part for part in url.split("/") if part]
    try:
        bbs_index = parts.index("bbs")
        return int(parts[bbs_index + 1])
    except (ValueError, IndexError):
        return 0


def _sleep(seconds: float) -> None:
    if seconds > 0:
        time.sleep(seconds)
