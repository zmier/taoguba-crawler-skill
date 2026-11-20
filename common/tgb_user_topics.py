from __future__ import annotations

from dataclasses import dataclass, replace
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
    max_article_details: int | None = 20
    comment_pages_per_article: int = 1
    all_comment_pages: bool = False
    skip_comments: bool = False
    author_comments_only: bool = False
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
    if not str(config.user_id).isdigit():
        raise ValueError("user_id_must_be_digits")
    if config.start_page < 1:
        raise ValueError("start_page_must_be_positive")
    if config.skip_comments and config.all_comment_pages:
        raise ValueError("skip_comments_conflicts_with_all_comment_pages")
    if not config.skip_comments and config.comment_pages_per_article < 1:
        raise ValueError("comment_pages_per_article_must_be_positive")
    if config.max_article_details is not None and config.max_article_details < 0:
        raise ValueError("max_article_details_must_be_non_negative_or_none")

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
        "comment_pages_reused": 0,
        "comment_pages_mode": (
            "skipped"
            if config.skip_comments
            else ("all" if config.all_comment_pages else "bounded")
        ),
        "author_comments_only": config.author_comments_only,
        "comments_seen": 0,
        "comments_excluded_other_users": 0,
        "comments_saved": 0,
        "queue_done": 0,
        "failures": 0,
    }

    try:
        if config.details_only:
            summary["total_pages"] = _stored_total_pages(conn, config.user_id)
            summary["article_tasks_enqueued"] = (
                enqueue_author_archive_gaps(conn, config.user_id)
                if config.author_comments_only and config.all_comment_pages
                else enqueue_missing_article_details(conn, config.user_id)
            )
            if config.fetch_article_details and _has_article_budget(config.max_article_details):
                _fetch_queued_article_details(conn, config, fetch_html, summary)
            summary["queue_done"] = conn.execute(
                "select count(*) from crawl_queue where status = 'done'"
            ).fetchone()[0]
            _finalize_comment_storage_summary(conn, config, summary)
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

        if config.author_comments_only and config.all_comment_pages:
            summary["article_tasks_enqueued"] = int(
                summary["article_tasks_enqueued"]
            ) + enqueue_author_archive_gaps(conn, config.user_id)

        if config.fetch_article_details and _has_article_budget(config.max_article_details):
            _fetch_queued_article_details(conn, config, fetch_html, summary)

        summary["queue_done"] = conn.execute(
            "select count(*) from crawl_queue where status = 'done'"
        ).fetchone()[0]
        _finalize_comment_storage_summary(conn, config, summary)
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
          and (
              a.fetched_at = ''
              or (trim(a.main_text) = '' and json_array_length(a.image_urls_json) = 0)
              or trim(a.main_html) = ''
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
        enqueued += _ensure_article_pending(conn, row["url"], priority)
    return enqueued


def enqueue_author_archive_gaps(conn: sqlite3.Connection, user_id: str) -> int:
    """Queue target-author posts whose detail or reported comment pages are incomplete."""

    rows = conn.execute(
        """
        select a.url, a.source_page,
               case
                 when a.fetched_at = '' then 1
                 when trim(a.title) = '' then 1
                 when trim(a.author) = '' then 1
                 when trim(a.author_id) <> ? then 1
                 when trim(a.main_text) = '' and json_array_length(a.image_urls_json) = 0 then 1
                 when trim(a.main_html) = '' then 1
                 when (select count(*) from article_pages p where p.article_slug = a.slug)
                      < max(1, a.comment_page_count) then 1
                 else 0
               end as needs_fetch
        from articles a
        where a.author_id = ?
        order by a.source_page asc, a.rowid asc
        """,
        (str(user_id), str(user_id)),
    ).fetchall()
    candidates = [row for row in rows if int(row["needs_fetch"] or 0) == 1]
    enqueued = 0
    for index, row in enumerate(candidates):
        priority = _record_priority(int(row["source_page"] or 0), index, len(candidates))
        enqueued += _ensure_article_pending(conn, row["url"], priority)
    return enqueued


def _ensure_article_pending(
    conn: sqlite3.Connection,
    url: str,
    priority: int,
) -> int:
    """Queue or requeue one incomplete legacy detail without duplicating work."""

    existing = conn.execute(
        "select status, last_error from crawl_queue where url = ? and kind = 'article'",
        (url,),
    ).fetchone()
    if existing is None:
        return 1 if enqueue(conn, url, kind="article", priority=priority) else 0
    if existing["status"] == "failed" and str(existing["last_error"] or "").startswith(
        "author_detail_user_id_mismatch:"
    ):
        # A repeated wrong-author result is an explicit source gap, not an empty
        # author detail that may be silently replaced or requeued forever.
        return 0
    if existing["status"] != "pending":
        conn.execute(
            """
            update crawl_queue
            set status = 'pending', priority = ?, attempts = 0,
                last_error = '', next_run_at = null, updated_at = datetime('now')
            where url = ? and kind = 'article'
            """,
            (priority, url),
        )
        conn.commit()
        return 1
    _refresh_pending_priority(conn, url, priority)
    return 0


def _fetch_queued_article_details(
    conn: sqlite3.Connection,
    config: UserTopicsConfig,
    fetch_html: FetchHtml,
    summary: dict[str, object],
) -> None:
    processed = 0
    while config.max_article_details is None or processed < config.max_article_details:
        task = claim_next(conn, kind="article")
        if task is None:
            return
        processed += 1
        url = task["url"]
        try:
            html = fetch_html(url)
            detail = parse_article_detail(html, url=url)
            if not detail.slug:
                raise ValueError(f"无法从 URL 解析帖子 slug: {url}")
            if config.author_comments_only:
                validate_author_archive_detail(
                    detail,
                    html=html,
                    expected_user_id=config.user_id,
                )
            upsert_article_detail(conn, detail)
            upsert_article_page(conn, detail.slug, 1, url, html)
            summary["article_details_fetched"] = int(summary["article_details_fetched"]) + 1
            if not config.skip_comments:
                comments = parse_comments(html, article_slug=detail.slug, page_no=1)
                selected = select_comments_for_storage(
                    comments,
                    target_user_id=config.user_id,
                    author_comments_only=config.author_comments_only,
                )
                upsert_comments(conn, selected)
                summary["comment_pages_fetched"] = int(summary["comment_pages_fetched"]) + 1
                summary["comments_seen"] = int(summary["comments_seen"]) + len(comments)
                summary["comments_excluded_other_users"] = int(
                    summary["comments_excluded_other_users"]
                ) + (len(comments) - len(selected))
                summary["comments_saved"] = int(summary["comments_saved"]) + len(selected)

                page_limit = (
                    max(1, detail.comment_page_count)
                    if config.all_comment_pages
                    else config.comment_pages_per_article
                )
                for page_no in range(2, page_limit + 1):
                    if conn.execute(
                        """
                        select 1 from article_pages
                        where article_slug=? and page_no=?
                          and html_sha256<>'' and fetched_at<>''
                        """,
                        (detail.slug, page_no),
                    ).fetchone():
                        summary["comment_pages_reused"] = int(
                            summary["comment_pages_reused"]
                        ) + 1
                        continue
                    comment_url = build_comment_page_url(detail.slug, page_no)
                    comment_html = fetch_html(comment_url)
                    page_comments = parse_comments(
                        comment_html, article_slug=detail.slug, page_no=page_no
                    )
                    selected = select_comments_for_storage(
                        page_comments,
                        target_user_id=config.user_id,
                        author_comments_only=config.author_comments_only,
                    )
                    upsert_comments(conn, selected)
                    upsert_article_page(
                        conn, detail.slug, page_no, comment_url, comment_html
                    )
                    summary["comment_pages_fetched"] = int(
                        summary["comment_pages_fetched"]
                    ) + 1
                    summary["comments_seen"] = int(summary["comments_seen"]) + len(
                        page_comments
                    )
                    summary["comments_excluded_other_users"] = int(
                        summary["comments_excluded_other_users"]
                    ) + (len(page_comments) - len(selected))
                    summary["comments_saved"] = int(summary["comments_saved"]) + len(
                        selected
                    )
                    _sleep(config.request_interval_seconds)
                if config.author_comments_only:
                    _prune_non_author_comments(conn, detail.slug, config.user_id)
            mark_done(conn, url)
        except AuthorArchiveAuthenticationError as exc:
            mark_failed(
                conn,
                url,
                error=str(exc),
                max_attempts=config.max_attempts,
                backoff_seconds=config.backoff_seconds,
            )
            raise
        except Exception as exc:
            mark_failed(
                conn,
                url,
                error=str(exc),
                max_attempts=config.max_attempts,
                backoff_seconds=config.backoff_seconds,
            )
        _sleep(config.request_interval_seconds)


class AuthorArchiveAuthenticationError(RuntimeError):
    """The requested author detail is unavailable under the current session."""


def validate_author_archive_detail(
    detail,
    *,
    html: str,
    expected_user_id: str,
) -> None:
    """Fail closed on redirects/previews/wrong-author pages in author-only mode."""

    expected = str(expected_user_id).strip()
    if "/user/generalUserCertPage" in (detail.url or "") or "登录可查看全文" in (html or ""):
        raise AuthorArchiveAuthenticationError("author_detail_login_or_preview_page")
    if not detail.title or not detail.author or not detail.main_html or not (detail.main_text or detail.image_urls):
        raise AuthorArchiveAuthenticationError("author_detail_required_fields_empty")
    if str(detail.author_id).strip() != expected:
        raise AuthorArchiveAuthenticationError(
            f"author_detail_user_id_mismatch:{detail.author_id}!={expected}"
        )


def select_comments_for_storage(
    comments,
    *,
    target_user_id: str,
    author_comments_only: bool,
):
    """Normalize author identity by immutable ID and optionally exclude all others."""

    target = str(target_user_id)
    normalized = [
        replace(comment, is_author=str(comment.user_id) == target)
        for comment in comments
    ]
    if not author_comments_only:
        return normalized
    return [comment for comment in normalized if str(comment.user_id) == target]


def _prune_non_author_comments(
    conn: sqlite3.Connection,
    article_slug: str,
    target_user_id: str,
) -> None:
    """Enforce author-only persistence even when reusing an older mixed database."""

    conn.execute(
        "delete from comments where article_slug = ? and user_id <> ?",
        (article_slug, str(target_user_id)),
    )
    conn.execute(
        "delete from comments where article_slug = ? and user_id = ''",
        (article_slug,),
    )
    conn.commit()


def _finalize_comment_storage_summary(
    conn: sqlite3.Connection,
    config: UserTopicsConfig,
    summary: dict[str, object],
) -> None:
    if config.author_comments_only:
        conn.execute(
            "delete from comments where user_id <> ? or user_id = ''",
            (str(config.user_id),),
        )
        conn.execute(
            "update comments set is_author = 1 where user_id = ?",
            (str(config.user_id),),
        )
        conn.commit()
    persisted = conn.execute(
        """
        select count(*) as total,
               sum(case when user_id = ? then 1 else 0 end) as target_rows,
               sum(case when user_id <> ? or user_id = '' then 1 else 0 end) as other_rows
        from comments
        """,
        (str(config.user_id), str(config.user_id)),
    ).fetchone()
    summary["persisted_comments"] = int(persisted["total"] or 0)
    summary["persisted_target_user_comments"] = int(persisted["target_rows"] or 0)
    summary["persisted_other_user_comments"] = int(persisted["other_rows"] or 0)
    summary["author_only_storage_green"] = bool(
        not config.author_comments_only
        or int(persisted["other_rows"] or 0) == 0
    )


def _has_article_budget(value: int | None) -> bool:
    return value is None or value > 0


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
