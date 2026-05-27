from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3
import time
from typing import Callable

from common.tgb_article import parse_article_detail
from common.tgb_comment import build_comment_page_url, parse_comments
from common.tgb_index import (
    BbsIndexRecord,
    build_bbs_page_url,
    parse_bbs_list,
    parse_bbs_pagination,
)
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
class StopPolicy:
    max_pages: int = 5
    known_article_threshold: int = 50
    no_new_page_threshold: int = 2


@dataclass(frozen=True)
class IncrementalScanState:
    pages_scanned: int = 0
    consecutive_known_articles: int = 0
    consecutive_no_new_pages: int = 0


@dataclass(frozen=True)
class StopDecision:
    stop: bool
    reason: str = ""


@dataclass(frozen=True)
class IncrementalConfig:
    db_path: Path
    start_page: int = 1
    flag: int = 1
    max_pages: int = 5
    max_article_details: int = 20
    max_refresh_articles: int = 20
    comment_pages_per_article: int = 1
    known_article_threshold: int = 50
    no_new_page_threshold: int = 2
    request_interval_seconds: float = 0.8
    max_attempts: int = 3
    backoff_seconds: int = 30


def should_stop_incremental(state: IncrementalScanState, policy: StopPolicy) -> StopDecision:
    if state.pages_scanned >= policy.max_pages:
        return StopDecision(True, "max_pages")
    if state.consecutive_known_articles >= policy.known_article_threshold:
        return StopDecision(True, "known_article_threshold")
    if state.consecutive_no_new_pages >= policy.no_new_page_threshold:
        return StopDecision(True, "no_new_page_threshold")
    return StopDecision(False, "")


def find_comment_refresh_candidates(conn: sqlite3.Connection, limit: int = 20) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        select
            a.slug,
            a.url,
            a.title,
            a.reply_count,
            count(c.reply_id) as comments_count,
            (a.reply_count - count(c.reply_id)) as missing_comments
        from articles a
        left join comments c on c.article_slug = a.slug
        where a.fetched_at != ''
        group by a.slug, a.url, a.title, a.reply_count
        having a.reply_count > count(c.reply_id)
        order by missing_comments desc, a.updated_at desc
        limit ?
        """,
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]


def run_incremental(config: IncrementalConfig, fetch_html: FetchHtml) -> dict[str, object]:
    conn = connect_db(config.db_path)
    init_db(conn)
    policy = StopPolicy(
        max_pages=config.max_pages,
        known_article_threshold=config.known_article_threshold,
        no_new_page_threshold=config.no_new_page_threshold,
    )
    state = IncrementalScanState()
    summary: dict[str, object] = {
        "mode": "incremental",
        "full_run": False,
        "db_path": str(config.db_path),
        "total_pages": 0,
        "list_pages_scanned": 0,
        "index_records_seen": 0,
        "new_articles": 0,
        "updated_articles": 0,
        "article_details_fetched": 0,
        "comment_refresh_candidates": 0,
        "comment_pages_fetched": 0,
        "comments_saved": 0,
        "queue_done": 0,
        "failures": 0,
        "stop_reason": "",
    }

    try:
        for page_no in range(config.start_page, config.start_page + config.max_pages):
            page_url = build_bbs_page_url(page_no, config.flag)
            html = fetch_html(page_url)
            pagination = parse_bbs_pagination(html, source_url=page_url)
            records = parse_bbs_list(html, source_url=page_url, source_page=page_no)
            page_stats = _classify_records(conn, records)
            upsert_index_records(conn, records)
            for record in page_stats["new_records"]:
                enqueue(conn, record.url, kind="article", priority=max(0, 1000 - page_no))

            summary["total_pages"] = max(int(summary["total_pages"]), pagination.total_pages)
            summary["list_pages_scanned"] = int(summary["list_pages_scanned"]) + 1
            summary["index_records_seen"] = int(summary["index_records_seen"]) + len(records)
            summary["new_articles"] = int(summary["new_articles"]) + len(page_stats["new_records"])
            summary["updated_articles"] = int(summary["updated_articles"]) + len(page_stats["updated_records"])

            state = IncrementalScanState(
                pages_scanned=int(summary["list_pages_scanned"]),
                consecutive_known_articles=page_stats["trailing_known_articles"],
                consecutive_no_new_pages=(
                    state.consecutive_no_new_pages + 1 if not page_stats["new_records"] else 0
                ),
            )
            decision = should_stop_incremental(state, policy)
            if decision.stop:
                summary["stop_reason"] = decision.reason
                break
            _sleep(config.request_interval_seconds)

        if not summary["stop_reason"]:
            summary["stop_reason"] = "scan_completed"

        _fetch_queued_articles(conn, config, fetch_html, summary)
        _refresh_recent_comments(conn, config, fetch_html, summary)
        summary["queue_done"] = conn.execute(
            "select count(*) from crawl_queue where status = 'done'"
        ).fetchone()[0]
        summary["failures"] = count_rows(conn, "failures")
        return summary
    finally:
        conn.close()


def _classify_records(conn: sqlite3.Connection, records: list[BbsIndexRecord]) -> dict[str, object]:
    new_records: list[BbsIndexRecord] = []
    updated_records: list[BbsIndexRecord] = []
    trailing_known_articles = 0
    for record in records:
        row = conn.execute(
            """
            select slug, reply_count, view_count, fetched_at
            from articles
            where slug = ?
            """,
            (record.slug,),
        ).fetchone()
        if row is None:
            new_records.append(record)
            trailing_known_articles = 0
            continue
        changed = row["reply_count"] != record.reply_count or row["view_count"] != record.view_count
        if changed:
            updated_records.append(record)
            trailing_known_articles = 0
        elif row["fetched_at"]:
            trailing_known_articles += 1
        else:
            trailing_known_articles = 0
    return {
        "new_records": new_records,
        "updated_records": updated_records,
        "trailing_known_articles": trailing_known_articles,
    }


def _fetch_queued_articles(
    conn: sqlite3.Connection,
    config: IncrementalConfig,
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


def _refresh_recent_comments(
    conn: sqlite3.Connection,
    config: IncrementalConfig,
    fetch_html: FetchHtml,
    summary: dict[str, object],
) -> None:
    candidates = find_comment_refresh_candidates(conn, limit=config.max_refresh_articles)
    summary["comment_refresh_candidates"] = len(candidates)
    for candidate in candidates:
        url = str(candidate["url"])
        slug = str(candidate["slug"])
        try:
            html = fetch_html(url)
            comments = parse_comments(html, article_slug=slug, page_no=1)
            upsert_comments(conn, comments)
            upsert_article_page(conn, slug, 1, url, html)
            summary["comment_pages_fetched"] = int(summary["comment_pages_fetched"]) + 1
            summary["comments_saved"] = int(summary["comments_saved"]) + len(comments)
        except Exception:
            continue
        _sleep(config.request_interval_seconds)


def _sleep(seconds: float) -> None:
    if seconds > 0:
        time.sleep(seconds)
