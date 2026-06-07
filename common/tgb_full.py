from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import sqlite3
import time
from typing import Callable
from urllib.parse import urldefrag

from common.tgb_article import parse_article_detail
from common.tgb_backfill import plan_comment_pages
from common.tgb_comment import build_comment_page_url, parse_comments
from common.tgb_guard import AntiBotBlocked, require_normal_page
from common.tgb_index import build_bbs_page_url, parse_bbs_list
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
class FullRunConfig:
    db_path: Path
    total_pages: int
    start_page: int | None = None
    end_page: int = 1
    flag: int = 1
    max_list_pages_per_run: int = 10
    max_articles_per_page: int = 20
    max_comment_pages_per_article: int = 5
    request_interval_seconds: float = 1.0
    max_attempts: int = 3
    backoff_seconds: int = 60
    production_full: bool = False
    manual_approval: bool = False


def plan_full_pages(config: FullRunConfig) -> list[int]:
    start_page = config.start_page or config.total_pages
    if config.total_pages < 1 or start_page < config.end_page:
        return []
    lower_bound = max(config.end_page, start_page - config.max_list_pages_per_run + 1)
    return list(range(start_page, lower_bound - 1, -1))


def validate_full_config(config: FullRunConfig) -> list[str]:
    issues: list[str] = []
    if config.total_pages < 1:
        issues.append("total_pages_required")
    if config.max_list_pages_per_run < 1:
        issues.append("max_list_pages_required")
    if config.max_articles_per_page < 1:
        issues.append("max_articles_per_page_required")
    if config.max_comment_pages_per_article < 1:
        issues.append("max_comment_pages_required")
    if config.production_full and not config.manual_approval:
        issues.append("manual_approval_required")
    return issues


def enqueue_full_trial_plan(conn: sqlite3.Connection, config: FullRunConfig) -> int:
    count = 0
    for page_no in plan_full_pages(config):
        if enqueue(conn, build_bbs_page_url(page_no, config.flag), kind="list_page", priority=page_no):
            count += 1
    return count


def run_full_trial(config: FullRunConfig, fetch_html: FetchHtml) -> dict[str, object]:
    issues = validate_full_config(config)
    if issues:
        raise ValueError(f"invalid full config: {', '.join(issues)}")

    conn = connect_db(config.db_path)
    init_db(conn)
    summary: dict[str, object] = {
        "mode": "full_trial",
        "full_run": False,
        "full_run_gate": "manual_approval_required",
        "direction": "reverse",
        "db_path": str(config.db_path),
        "total_pages": config.total_pages,
        "planned_pages": plan_full_pages(config),
        "list_page_tasks_enqueued": 0,
        "list_pages_done": 0,
        "index_records_seen": 0,
        "article_tasks_enqueued": 0,
        "article_details_fetched": 0,
        "comment_page_tasks_enqueued": 0,
        "comment_pages_fetched": 0,
        "comments_seen": 0,
        "queue_done": 0,
        "failures": 0,
        "estimated_remaining_pages": 0,
        "stop_reason": "",
    }

    try:
        summary["list_page_tasks_enqueued"] = enqueue_full_trial_plan(conn, config)
        _process_list_pages(conn, config, fetch_html, summary)
        if summary["stop_reason"] != "anti_bot_blocked":
            _process_article_pages(conn, config, fetch_html, summary)
        if summary["stop_reason"] != "anti_bot_blocked":
            _process_comment_pages(conn, config, fetch_html, summary)
        summary["queue_done"] = conn.execute(
            "select count(*) from crawl_queue where status = 'done'"
        ).fetchone()[0]
        summary["failures"] = count_rows(conn, "failures")
        summary["estimated_remaining_pages"] = max(
            0,
            (config.start_page or config.total_pages) - int(summary["list_pages_done"]) - config.end_page + 1,
        )
        if not summary["stop_reason"]:
            summary["stop_reason"] = "trial_limits_reached"
        return build_full_run_report(summary)
    finally:
        conn.close()


def run_full_batch(config: FullRunConfig, fetch_html: FetchHtml) -> dict[str, object]:
    approved_config = FullRunConfig(
        db_path=config.db_path,
        total_pages=config.total_pages,
        start_page=config.start_page,
        end_page=config.end_page,
        flag=config.flag,
        max_list_pages_per_run=config.max_list_pages_per_run,
        max_articles_per_page=config.max_articles_per_page,
        max_comment_pages_per_article=config.max_comment_pages_per_article,
        request_interval_seconds=config.request_interval_seconds,
        max_attempts=config.max_attempts,
        backoff_seconds=config.backoff_seconds,
        production_full=True,
        manual_approval=config.manual_approval,
    )
    report = run_full_trial(approved_config, fetch_html)
    report["mode"] = "full_batch"
    report["full_run"] = True
    report["full_run_gate"] = "manual_approval_granted"
    report["manual_approval"] = True
    return report


def build_full_run_report(summary: dict[str, object]) -> dict[str, object]:
    report = dict(summary)
    report.setdefault("full_run_gate", "manual_approval_required")
    return report


def _process_list_pages(
    conn: sqlite3.Connection,
    config: FullRunConfig,
    fetch_html: FetchHtml,
    summary: dict[str, object],
) -> None:
    while True:
        task = claim_next(conn, kind="list_page")
        if task is None:
            return
        queue_url = task["url"]
        try:
            html = fetch_html(queue_url)
            require_normal_page(html, queue_url, expected="bbs_list")
            page_no = _page_no_from_bbs_url(queue_url)
            records = parse_bbs_list(html, source_url=queue_url, source_page=page_no)
            upsert_index_records(conn, records)
            selected = records[-config.max_articles_per_page :] if config.max_articles_per_page else []
            for record in selected:
                if enqueue(conn, record.url, kind="article", priority=page_no):
                    summary["article_tasks_enqueued"] = int(summary["article_tasks_enqueued"]) + 1
            summary["list_pages_done"] = int(summary["list_pages_done"]) + 1
            summary["index_records_seen"] = int(summary["index_records_seen"]) + len(records)
            mark_done(conn, queue_url)
        except Exception as exc:
            mark_failed(conn, queue_url, str(exc), config.max_attempts, config.backoff_seconds)
            if isinstance(exc, AntiBotBlocked):
                summary["stop_reason"] = "anti_bot_blocked"
                return
        _sleep(config.request_interval_seconds)


def _process_article_pages(
    conn: sqlite3.Connection,
    config: FullRunConfig,
    fetch_html: FetchHtml,
    summary: dict[str, object],
) -> None:
    while True:
        task = claim_next(conn, kind="article")
        if task is None:
            return
        queue_url = task["url"]
        try:
            html = fetch_html(queue_url)
            require_normal_page(html, queue_url, expected="article")
            detail = parse_article_detail(html, url=queue_url)
            if not detail.slug:
                raise ValueError(f"无法从 URL 解析帖子 slug: {queue_url}")
            upsert_article_detail(conn, detail)
            summary["article_details_fetched"] = int(summary["article_details_fetched"]) + 1
            for page_no in plan_comment_pages(detail.comment_page_count, config.max_comment_pages_per_article):
                comment_url = _queue_comment_url(detail.slug, page_no)
                if enqueue(conn, comment_url, kind="comment_page", priority=page_no):
                    summary["comment_page_tasks_enqueued"] = int(summary["comment_page_tasks_enqueued"]) + 1
            mark_done(conn, queue_url)
        except Exception as exc:
            mark_failed(conn, queue_url, str(exc), config.max_attempts, config.backoff_seconds)
            if isinstance(exc, AntiBotBlocked):
                summary["stop_reason"] = "anti_bot_blocked"
                return
        _sleep(config.request_interval_seconds)


def _process_comment_pages(
    conn: sqlite3.Connection,
    config: FullRunConfig,
    fetch_html: FetchHtml,
    summary: dict[str, object],
) -> None:
    while True:
        task = claim_next(conn, kind="comment_page")
        if task is None:
            return
        queue_url = task["url"]
        fetch_url, _ = urldefrag(queue_url)
        slug, page_no = _comment_info_from_url(queue_url)
        try:
            html = fetch_html(fetch_url)
            require_normal_page(html, fetch_url, expected="comment_page")
            comments = parse_comments(html, article_slug=slug, page_no=page_no)
            upsert_comments(conn, comments)
            upsert_article_page(conn, slug, page_no, fetch_url, html)
            summary["comment_pages_fetched"] = int(summary["comment_pages_fetched"]) + 1
            summary["comments_seen"] = int(summary["comments_seen"]) + len(comments)
            mark_done(conn, queue_url)
        except Exception as exc:
            mark_failed(conn, queue_url, str(exc), config.max_attempts, config.backoff_seconds)
            if isinstance(exc, AntiBotBlocked):
                summary["stop_reason"] = "anti_bot_blocked"
                return
        _sleep(config.request_interval_seconds)


def _queue_comment_url(slug: str, page_no: int) -> str:
    return f"{build_comment_page_url(slug, page_no)}#comment-page-{page_no}"


def _comment_info_from_url(url: str) -> tuple[str, int]:
    fetch_url, fragment = urldefrag(url)
    match = re.search(r"/a/([^/?#-]+)(?:-(\d+))?", fetch_url)
    slug = match.group(1) if match else ""
    page_no = int(match.group(2) or "1") if match else 1
    fragment_match = re.search(r"comment-page-(\d+)", fragment)
    if fragment_match:
        page_no = int(fragment_match.group(1))
    return slug, page_no


def _page_no_from_bbs_url(url: str) -> int:
    match = re.search(r"/bbs/(\d+)/", url)
    return int(match.group(1)) if match else 0


def _sleep(seconds: float) -> None:
    if seconds > 0:
        time.sleep(seconds)
