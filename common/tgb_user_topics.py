from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import sqlite3
import time
from typing import Callable
from urllib.parse import urlencode

from common.tgb_article import parse_article_detail
from common.tgb_comment import build_comment_page_url, parse_comments
from common.tgb_index import BASE_URL, BbsIndexRecord, parse_bbs_list
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
class UserTopicPagination:
    user_id: str
    current_page: int
    total_pages: int
    latest_url: str
    last_url: str


@dataclass(frozen=True)
class UserTopicsConfig:
    db_path: Path
    user_id: str
    start_page: int = 1
    end_page: int | None = None
    max_pages: int | None = 1
    details_only: bool = False
    fetch_article_details: bool = False
    max_article_details: int = 20
    comment_pages_per_article: int = 1
    request_interval_seconds: float = 1.0
    max_attempts: int = 3
    backoff_seconds: int = 30


def build_user_topic_page_url(user_id: str | int, page_no: int = 1, sort_flag: str = "") -> str:
    params = {"userID": str(user_id), "pageNo": str(page_no)}
    if sort_flag:
        params["sortFlag"] = sort_flag
    return f"{BASE_URL}/user/blog/moreTopic?{urlencode(params)}"


def parse_user_topic_pagination(html: str, source_url: str = "", user_id: str = "") -> UserTopicPagination:
    resolved_user_id = user_id or _user_id_from_url(source_url) or _first_match(html, r"userID=(\d+)")
    current_page = _page_no_from_url(source_url) or _page_no_from_form(html) or 1
    total_pages = _total_pages_from_html(html) or current_page
    return UserTopicPagination(
        user_id=resolved_user_id,
        current_page=current_page,
        total_pages=total_pages,
        latest_url=build_user_topic_page_url(resolved_user_id, 1),
        last_url=build_user_topic_page_url(resolved_user_id, total_pages),
    )


def plan_user_topic_pages(
    total_pages: int,
    start_page: int = 1,
    end_page: int | None = None,
    max_pages: int | None = None,
) -> list[int]:
    if total_pages < 1 or start_page < 1:
        return []
    upper = min(end_page or total_pages, total_pages)
    if start_page > upper:
        return []
    pages = list(range(start_page, upper + 1))
    if max_pages is not None:
        pages = pages[: max(0, max_pages)]
    return pages


def run_user_topics(config: UserTopicsConfig, fetch_html: FetchHtml) -> dict[str, object]:
    if not str(config.user_id).strip():
        raise ValueError("user_id_required")
    if config.start_page < 1:
        raise ValueError("start_page_must_be_positive")
    if config.comment_pages_per_article < 1:
        raise ValueError("comment_pages_per_article_must_be_positive")

    conn = connect_db(config.db_path)
    init_db(conn)
    summary: dict[str, object] = {
        "mode": "user_topics",
        "full_run": bool(config.max_pages is None and config.end_page is None),
        "db_path": str(config.db_path),
        "user_id": str(config.user_id),
        "total_pages": 0,
        "planned_pages": [],
        "list_pages_fetched": 0,
        "index_records_seen": 0,
        "index_records_saved": 0,
        "article_tasks_enqueued": 0,
        "article_details_fetched": 0,
        "comment_pages_fetched": 0,
        "comments_saved": 0,
        "queue_done": 0,
        "failures": 0,
    }

    try:
        if config.details_only:
            summary["total_pages"] = _stored_total_pages(conn, config.user_id)
            summary["article_tasks_enqueued"] = enqueue_missing_article_details(conn, config.user_id)
            if config.fetch_article_details and config.max_article_details > 0:
                _fetch_queued_article_details(conn, config, fetch_html, summary)
            summary["queue_done"] = conn.execute(
                "select count(*) from crawl_queue where status = 'done'"
            ).fetchone()[0]
            summary["failures"] = count_rows(conn, "failures")
            return summary

        first_url = build_user_topic_page_url(config.user_id, config.start_page)
        first_html = fetch_html(first_url)
        pagination = parse_user_topic_pagination(first_html, source_url=first_url, user_id=str(config.user_id))
        pages = plan_user_topic_pages(
            pagination.total_pages,
            start_page=config.start_page,
            end_page=config.end_page,
            max_pages=config.max_pages,
        )
        summary["total_pages"] = pagination.total_pages
        summary["planned_pages"] = pages

        html_cache = {config.start_page: first_html}
        for page_no in pages:
            page_url = build_user_topic_page_url(config.user_id, page_no)
            html = html_cache.get(page_no)
            if html is None:
                html = fetch_html(page_url)

            records = [
                record
                for record in parse_bbs_list(html, source_url=page_url, source_page=page_no)
                if not record.author_id or record.author_id == str(config.user_id)
            ]
            saved = upsert_index_records(conn, records)
            summary["list_pages_fetched"] = int(summary["list_pages_fetched"]) + 1
            summary["index_records_seen"] = int(summary["index_records_seen"]) + len(records)
            summary["index_records_saved"] = int(summary["index_records_saved"]) + saved

            if config.fetch_article_details:
                for index, record in enumerate(records):
                    priority = _record_priority(page_no, index, len(records))
                    if enqueue(conn, record.url, kind="article", priority=priority):
                        summary["article_tasks_enqueued"] = int(summary["article_tasks_enqueued"]) + 1
                    else:
                        _refresh_pending_priority(conn, record.url, priority)
            _sleep(config.request_interval_seconds)

        if config.fetch_article_details and config.max_article_details > 0:
            _fetch_queued_article_details(conn, config, fetch_html, summary)

        summary["queue_done"] = conn.execute(
            "select count(*) from crawl_queue where status = 'done'"
        ).fetchone()[0]
        summary["failures"] = count_rows(conn, "failures")
        return summary
    finally:
        conn.close()


def enqueue_missing_article_details(conn: sqlite3.Connection, user_id: str) -> int:
    rows = conn.execute(
        """
        select slug, url, source_page
        from articles a
        where a.author_id = ?
          and a.fetched_at = ''
          and not exists (
              select 1
              from crawl_queue q
              where q.url = a.url
                and q.kind = 'article'
          )
        order by a.source_page asc, a.rowid asc
        """,
        (str(user_id),),
    ).fetchall()
    enqueued = 0
    total = len(rows)
    for index, row in enumerate(rows):
        page_no = int(row["source_page"] or 0)
        priority = _record_priority(page_no, index, total)
        if enqueue(conn, row["url"], kind="article", priority=priority):
            enqueued += 1
    return enqueued


def _fetch_queued_article_details(
    conn: sqlite3.Connection,
    config: UserTopicsConfig,
    fetch_html: FetchHtml,
    summary: dict[str, object],
) -> None:
    for _ in range(config.max_article_details):
        task = claim_next(conn, kind="article")
        if task is None:
            return
        url = task["url"]
        try:
            html = fetch_html(url)
            detail = parse_article_detail(html, url=url)
            if not detail.slug:
                raise ValueError(f"无法从 URL 解析帖子 slug: {url}")
            upsert_article_detail(conn, detail)
            upsert_article_page(conn, detail.slug, 1, url, html)
            comments = parse_comments(html, article_slug=detail.slug, page_no=1)
            upsert_comments(conn, comments)
            summary["article_details_fetched"] = int(summary["article_details_fetched"]) + 1
            summary["comment_pages_fetched"] = int(summary["comment_pages_fetched"]) + 1
            summary["comments_saved"] = int(summary["comments_saved"]) + len(comments)

            for page_no in range(2, config.comment_pages_per_article + 1):
                comment_url = build_comment_page_url(detail.slug, page_no)
                comment_html = fetch_html(comment_url)
                page_comments = parse_comments(comment_html, article_slug=detail.slug, page_no=page_no)
                upsert_comments(conn, page_comments)
                upsert_article_page(conn, detail.slug, page_no, comment_url, comment_html)
                summary["comment_pages_fetched"] = int(summary["comment_pages_fetched"]) + 1
                summary["comments_saved"] = int(summary["comments_saved"]) + len(page_comments)
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


def _total_pages_from_html(html: str) -> int:
    values = [int(value) for value in re.findall(r"\bpageNum\s*=\s*(\d+)", html or "")]
    values.extend(int(value) for value in re.findall(r'data-page-no=["\'](\d+)["\']', html or ""))
    return max(values) if values else 0


def _stored_total_pages(conn: sqlite3.Connection, user_id: str) -> int:
    row = conn.execute(
        """
        select max(source_page) as total_pages
        from articles
        where author_id = ?
        """,
        (str(user_id),),
    ).fetchone()
    return int(row["total_pages"] or 0) if row is not None else 0


def _record_priority(page_no: int, index: int, records_count: int) -> int:
    page_weight = max(0, 10000 - page_no) * 1000
    position_weight = max(0, records_count - index)
    return page_weight + position_weight


def _refresh_pending_priority(conn: sqlite3.Connection, url: str, priority: int) -> None:
    conn.execute(
        """
        update crawl_queue
        set priority = ?
        where url = ? and status = 'pending'
        """,
        (priority, url),
    )
    conn.commit()


def _page_no_from_form(html: str) -> int:
    value = _first_match(html, r'name=["\']pageNo["\']\s+value=["\']?(\d+)')
    return int(value) if value else 0


def _page_no_from_url(url: str) -> int:
    value = _first_match(url, r"[?&]pageNo=(\d+)")
    return int(value) if value else 0


def _user_id_from_url(url: str) -> str:
    return _first_match(url, r"[?&]userID=(\d+)")


def _first_match(text: str, pattern: str) -> str:
    match = re.search(pattern, text or "")
    return match.group(1) if match else ""


def _sleep(seconds: float) -> None:
    if seconds > 0:
        time.sleep(seconds)
