#!/usr/bin/env python3
"""Capture one TGB user's reply feed and resolve target-author full text."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
from urllib.parse import urlparse

import requests


PROJECT_ROOT = Path(__file__).resolve().parents[1]
IMAGE_MARKER = "［图片］"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app_common import load_env_file  # noqa: E402
from common.tgb_comment import parse_comments, recover_comment_text  # noqa: E402
from common.tgb_user_replies import (  # noqa: E402
    LOGIN_MARKERS,
    LOGIN_PATHS,
    UserReplyAuthenticationError,
    UserReplyFeedRecord,
    UserReplyStructureError,
    build_reply_detail_url,
    build_user_reply_feed_url,
    clean_author_full_text,
    contains_face_marker,
    display_matches_full_text,
    parse_feed_total_pages,
    parse_user_reply_feed,
    select_unique_target_reply,
    validate_feed_page,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def connect_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("pragma journal_mode=wal")
    conn.executescript(
        """
        create table if not exists user_reply_feed_page_receipts (
          user_id text not null, anchor_date text not null, page_no integer not null,
          page_url text not null, final_url text not null, html_sha256 text not null,
          row_count integer not null, total_pages integer not null,
          captured_at text not null, primary key(user_id,anchor_date,page_no)
        );
        create table if not exists user_reply_feed_page_items (
          user_id text not null, anchor_date text not null, page_no integer not null,
          position integer not null, username text not null, reply_id text not null,
          reply_created_at text not null, article_slug text not null,
          article_title text not null, article_url text not null, reply_url text not null,
          reply_text text not null, displayed_char_count integer, like_count integer,
          avatar_url text not null, row_html text not null default '',
          captured_at text not null,
          primary key(user_id,anchor_date,page_no,reply_id)
        );
        create table if not exists user_reply_feed_items (
          user_id text not null, username text not null, reply_id text not null,
          reply_created_at text not null, article_slug text not null,
          article_title text not null, article_url text not null, reply_url text not null,
          reply_text text not null, displayed_char_count integer, like_count integer,
          avatar_url text not null, source_page integer not null, position integer not null,
          anchor_date text not null, row_html text not null default '',
          captured_at text not null, primary key(user_id,reply_id)
        );
        create table if not exists user_reply_feed_capture_receipts (
          user_id text not null, anchor_date text not null, expected_pages integer not null,
          captured_pages integer not null, records_seen integer not null,
          unique_records integer not null, duplicate_occurrences integer not null,
          captured_at text not null, primary key(user_id,anchor_date)
        );
        create table if not exists user_reply_feed_incremental_receipts (
          user_id text not null, anchor_date text not null,
          total_pages integer not null, scanned_pages integer not null,
          baseline_records integer not null, records_seen integer not null,
          new_records integer not null, updated_records integer not null,
          current_records integer not null, stop_reason text not null,
          boundary_closed integer not null, captured_at text not null,
          primary key(user_id,anchor_date)
        );
        create table if not exists user_reply_feed_item_revisions (
          id integer primary key autoincrement, user_id text not null,
          reply_id text not null, anchor_date text not null,
          change_type text not null,
          prior_feed_json text not null, current_feed_json text not null,
          prior_full_text_json text not null default '',
          detected_at text not null
        );
        create table if not exists user_reply_feed_failures (
          id integer primary key autoincrement, user_id text not null,
          anchor_date text not null, page_no integer not null, error_type text not null,
          error_message text not null, failed_at text not null,
          resolved_at text not null default ''
        );
        create table if not exists user_reply_feed_full_texts (
          user_id text not null, reply_id text not null, article_slug text not null,
          full_text text not null, full_text_html text not null,
          image_urls_json text not null, text_source text not null,
          source_url text not null, source_database_sha256 text not null default '',
          full_text_sha256 text not null, display_prefix_verified integer not null,
          resolved_at text not null, primary key(user_id,reply_id)
        );
        create table if not exists user_reply_detail_failures (
          id integer primary key autoincrement, user_id text not null,
          reply_id text not null, article_slug text not null, error_type text not null,
          error_message text not null, failed_at text not null,
          resolved_at text not null default ''
        );
        """
    )
    conn.commit()
    return conn


def request_html(session: requests.Session, url: str, timeout: float) -> tuple[str, str]:
    response = session.get(url, timeout=timeout)
    response.raise_for_status()
    response.encoding = "utf-8"
    return response.text, response.url


def store_page(
    conn: sqlite3.Connection,
    *,
    user_id: str,
    anchor_date: str,
    page_no: int,
    page_url: str,
    final_url: str,
    html: str,
    records: list[UserReplyFeedRecord],
    total_pages: int,
) -> None:
    captured_at = utc_now()
    with conn:
        conn.execute(
            "delete from user_reply_feed_page_items where user_id=? and anchor_date=? and page_no=?",
            (user_id, anchor_date, page_no),
        )
        conn.executemany(
            """
            insert into user_reply_feed_page_items (
              user_id,anchor_date,page_no,position,username,reply_id,
              reply_created_at,article_slug,article_title,article_url,reply_url,
              reply_text,displayed_char_count,like_count,avatar_url,row_html,captured_at
            ) values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'',?)
            """,
            [
                (
                    row.user_id,
                    anchor_date,
                    page_no,
                    row.position,
                    row.username,
                    row.reply_id,
                    row.reply_created_at,
                    row.article_slug,
                    row.article_title,
                    row.article_url,
                    row.reply_url,
                    row.author_display_text,
                    row.displayed_char_count,
                    row.like_count,
                    row.avatar_url,
                    captured_at,
                )
                for row in records
            ],
        )
        conn.execute(
            """
            insert into user_reply_feed_page_receipts
              (user_id,anchor_date,page_no,page_url,final_url,html_sha256,
               row_count,total_pages,captured_at)
            values (?,?,?,?,?,?,?,?,?)
            on conflict(user_id,anchor_date,page_no) do update set
              page_url=excluded.page_url,final_url=excluded.final_url,
              html_sha256=excluded.html_sha256,row_count=excluded.row_count,
              total_pages=excluded.total_pages,captured_at=excluded.captured_at
            """,
            (
                user_id,
                anchor_date,
                page_no,
                page_url,
                final_url,
                hashlib.sha256(html.encode("utf-8")).hexdigest(),
                len(records),
                total_pages,
                captured_at,
            ),
        )
        conn.execute(
            """
            update user_reply_feed_failures set resolved_at=?
            where user_id=? and anchor_date=? and page_no=? and resolved_at=''
            """,
            (captured_at, user_id, anchor_date, page_no),
        )


def finalize_feed(
    conn: sqlite3.Connection, *, user_id: str, anchor_date: str, total_pages: int
) -> dict[str, int]:
    receipts = conn.execute(
        """
        select page_no,total_pages from user_reply_feed_page_receipts
        where user_id=? and anchor_date=? order by page_no
        """,
        (user_id, anchor_date),
    ).fetchall()
    if [int(row["page_no"]) for row in receipts] != list(range(1, total_pages + 1)):
        raise UserReplyStructureError("reply_feed_incomplete_page_receipts")
    if any(int(row["total_pages"]) != total_pages for row in receipts):
        raise UserReplyStructureError("reply_feed_total_page_drift")
    rows = conn.execute(
        """
        select * from user_reply_feed_page_items
        where user_id=? and anchor_date=? order by page_no,position
        """,
        (user_id, anchor_date),
    ).fetchall()
    canonical: dict[str, sqlite3.Row] = {}
    duplicate_occurrences = 0
    for row in rows:
        prior = canonical.get(row["reply_id"])
        if prior is None:
            canonical[row["reply_id"]] = row
            continue
        duplicate_occurrences += 1
        identity = lambda item: (
            item["article_slug"],
            item["reply_created_at"],
            item["reply_text"],
            item["username"],
        )
        if identity(prior) != identity(row):
            raise UserReplyStructureError(
                f"reply_feed_conflicting_duplicate:{row['reply_id']}"
            )
    captured_at = utc_now()
    with conn:
        conn.execute("delete from user_reply_feed_items where user_id=?", (user_id,))
        conn.executemany(
            """
            insert into user_reply_feed_items (
              user_id,username,reply_id,reply_created_at,article_slug,article_title,
              article_url,reply_url,reply_text,displayed_char_count,like_count,
              avatar_url,source_page,position,anchor_date,row_html,captured_at
            ) values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'',?)
            """,
            [
                (
                    row["user_id"],
                    row["username"],
                    row["reply_id"],
                    row["reply_created_at"],
                    row["article_slug"],
                    row["article_title"],
                    row["article_url"],
                    row["reply_url"],
                    row["reply_text"],
                    row["displayed_char_count"],
                    row["like_count"],
                    row["avatar_url"],
                    row["page_no"],
                    row["position"],
                    anchor_date,
                    captured_at,
                )
                for row in canonical.values()
            ],
        )
        conn.execute(
            """
            insert into user_reply_feed_capture_receipts
              (user_id,anchor_date,expected_pages,captured_pages,records_seen,
               unique_records,duplicate_occurrences,captured_at)
            values (?,?,?,?,?,?,?,?)
            on conflict(user_id,anchor_date) do update set
              expected_pages=excluded.expected_pages,captured_pages=excluded.captured_pages,
              records_seen=excluded.records_seen,unique_records=excluded.unique_records,
              duplicate_occurrences=excluded.duplicate_occurrences,
              captured_at=excluded.captured_at
            """,
            (
                user_id,
                anchor_date,
                total_pages,
                len(receipts),
                len(rows),
                len(canonical),
                duplicate_occurrences,
                captured_at,
            ),
        )
    return {
        "records_seen": len(rows),
        "unique_records": len(canonical),
        "duplicate_occurrences": duplicate_occurrences,
    }


def known_reply_ids(conn: sqlite3.Connection, user_id: str) -> set[str]:
    return {
        str(row[0])
        for row in conn.execute(
            "select reply_id from user_reply_feed_items where user_id=?",
            (user_id,),
        )
    }


def advance_known_reply_streak(
    records: list[UserReplyFeedRecord],
    *,
    baseline_reply_ids: set[str],
    current_streak: int = 0,
) -> tuple[int, set[str]]:
    """Advance the newest-to-oldest known-ID boundary for one feed page."""

    streak = current_streak
    new_ids: set[str] = set()
    for record in records:
        if record.reply_id in baseline_reply_ids:
            streak += 1
        else:
            new_ids.add(record.reply_id)
            streak = 0
    return streak, new_ids


def _feed_payload(row: sqlite3.Row) -> dict[str, object]:
    keys = set(row.keys())
    payload = {
        key: row[key]
        for key in (
            "user_id",
            "username",
            "reply_id",
            "reply_created_at",
            "article_slug",
            "article_title",
            "article_url",
            "reply_url",
            "reply_text",
            "displayed_char_count",
            "like_count",
            "avatar_url",
            "position",
            "anchor_date",
            "captured_at",
        )
    }
    payload["source_page"] = row["source_page"] if "source_page" in keys else row["page_no"]
    return payload


def merge_incremental_feed(
    conn: sqlite3.Connection,
    *,
    user_id: str,
    anchor_date: str,
    scanned_pages: int,
) -> dict[str, object]:
    """Merge a prefix scan into the canonical reply feed without dropping history."""

    rows = conn.execute(
        """
        select * from user_reply_feed_page_items
        where user_id=? and anchor_date=? and page_no<=?
        order by page_no,position
        """,
        (user_id, anchor_date, scanned_pages),
    ).fetchall()
    canonical: dict[str, sqlite3.Row] = {}
    duplicate_occurrences = 0
    for row in rows:
        prior = canonical.get(str(row["reply_id"]))
        if prior is None:
            canonical[str(row["reply_id"])] = row
            continue
        duplicate_occurrences += 1
        identity = lambda item: (
            item["article_slug"],
            item["reply_created_at"],
            item["reply_text"],
            item["username"],
        )
        if identity(prior) != identity(row):
            raise UserReplyStructureError(
                f"reply_feed_conflicting_duplicate:{row['reply_id']}"
            )

    new_ids: list[str] = []
    updated_ids: list[str] = []
    unchanged = 0
    detected_at = utc_now()
    with conn:
        for row in canonical.values():
            existing = conn.execute(
                "select * from user_reply_feed_items where user_id=? and reply_id=?",
                (user_id, row["reply_id"]),
            ).fetchone()
            semantic_changed = False
            if existing is None:
                new_ids.append(str(row["reply_id"]))
            else:
                invariant = lambda item: (
                    item["article_slug"], item["reply_created_at"], item["username"]
                )
                if invariant(existing) != invariant(row):
                    raise UserReplyStructureError(
                        f"reply_feed_incremental_identity_drift:{row['reply_id']}"
                    )
                semantic_changed = any(
                    existing[key] != row[key]
                    for key in (
                        "article_title",
                        "article_url",
                        "reply_url",
                        "reply_text",
                        "displayed_char_count",
                    )
                )
                if semantic_changed:
                    prior_full = conn.execute(
                        """
                        select * from user_reply_feed_full_texts
                        where user_id=? and reply_id=?
                        """,
                        (user_id, row["reply_id"]),
                    ).fetchone()
                    conn.execute(
                        """
                        insert into user_reply_feed_item_revisions (
                          user_id,reply_id,anchor_date,change_type,
                          prior_feed_json,current_feed_json,prior_full_text_json,
                          detected_at
                        ) values (?,?,?,?,?,?,?,?)
                        """,
                        (
                            user_id,
                            row["reply_id"],
                            anchor_date,
                            "feed-display-changed",
                            json.dumps(_feed_payload(existing), ensure_ascii=False),
                            json.dumps(_feed_payload(row), ensure_ascii=False),
                            (
                                json.dumps(dict(prior_full), ensure_ascii=False)
                                if prior_full is not None
                                else ""
                            ),
                            detected_at,
                        ),
                    )
                    conn.execute(
                        "delete from user_reply_feed_full_texts where user_id=? and reply_id=?",
                        (user_id, row["reply_id"]),
                    )
                    updated_ids.append(str(row["reply_id"]))
                else:
                    unchanged += 1
            conn.execute(
                """
                insert into user_reply_feed_items (
                  user_id,username,reply_id,reply_created_at,article_slug,article_title,
                  article_url,reply_url,reply_text,displayed_char_count,like_count,
                  avatar_url,source_page,position,anchor_date,row_html,captured_at
                ) values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'',?)
                on conflict(user_id,reply_id) do update set
                  username=excluded.username,reply_created_at=excluded.reply_created_at,
                  article_slug=excluded.article_slug,article_title=excluded.article_title,
                  article_url=excluded.article_url,reply_url=excluded.reply_url,
                  reply_text=excluded.reply_text,
                  displayed_char_count=excluded.displayed_char_count,
                  like_count=excluded.like_count,avatar_url=excluded.avatar_url,
                  source_page=excluded.source_page,position=excluded.position,
                  anchor_date=excluded.anchor_date,row_html='',captured_at=excluded.captured_at
                """,
                (
                    row["user_id"],
                    row["username"],
                    row["reply_id"],
                    row["reply_created_at"],
                    row["article_slug"],
                    row["article_title"],
                    row["article_url"],
                    row["reply_url"],
                    row["reply_text"],
                    row["displayed_char_count"],
                    row["like_count"],
                    row["avatar_url"],
                    row["page_no"],
                    row["position"],
                    anchor_date,
                    detected_at,
                ),
            )
    current_records = int(
        conn.execute(
            "select count(*) from user_reply_feed_items where user_id=?", (user_id,)
        ).fetchone()[0]
    )
    return {
        "records_seen": len(rows),
        "unique_records": len(canonical),
        "duplicate_occurrences": duplicate_occurrences,
        "new_records": len(new_ids),
        "new_reply_ids": new_ids,
        "updated_records": len(updated_ids),
        "updated_reply_ids": updated_ids,
        "unchanged_records": unchanged,
        "current_records": current_records,
    }


def record_incremental_receipt(
    conn: sqlite3.Connection,
    *,
    user_id: str,
    anchor_date: str,
    total_pages: int,
    scanned_pages: int,
    baseline_records: int,
    merge_stats: dict[str, object],
    stop_reason: str,
    boundary_closed: bool,
) -> None:
    with conn:
        conn.execute(
            """
            insert into user_reply_feed_incremental_receipts (
              user_id,anchor_date,total_pages,scanned_pages,baseline_records,
              records_seen,new_records,updated_records,current_records,
              stop_reason,boundary_closed,captured_at
            ) values (?,?,?,?,?,?,?,?,?,?,?,?)
            on conflict(user_id,anchor_date) do update set
              total_pages=excluded.total_pages,scanned_pages=excluded.scanned_pages,
              baseline_records=excluded.baseline_records,
              records_seen=excluded.records_seen,new_records=excluded.new_records,
              updated_records=excluded.updated_records,
              current_records=excluded.current_records,
              stop_reason=excluded.stop_reason,
              boundary_closed=excluded.boundary_closed,
              captured_at=excluded.captured_at
            """,
            (
                user_id,
                anchor_date,
                total_pages,
                scanned_pages,
                baseline_records,
                int(merge_stats.get("records_seen", 0)),
                int(merge_stats.get("new_records", 0)),
                int(merge_stats.get("updated_records", 0)),
                int(merge_stats.get("current_records", 0)),
                stop_reason,
                int(boundary_closed),
                utc_now(),
            ),
        )


def upsert_full_text(
    conn: sqlite3.Connection,
    *,
    user_id: str,
    reply_id: str,
    article_slug: str,
    text: str,
    html: str,
    image_urls: list[str],
    text_source: str,
    source_url: str,
    source_database_sha256: str = "",
) -> None:
    clean_text = clean_author_full_text(text)
    resolved_at = utc_now()
    conn.execute(
        """
        insert into user_reply_feed_full_texts (
          user_id,reply_id,article_slug,full_text,full_text_html,image_urls_json,
          text_source,source_url,source_database_sha256,full_text_sha256,
          display_prefix_verified,resolved_at
        ) values (?,?,?,?,?,?,?,?,?,?,1,?)
        on conflict(user_id,reply_id) do update set
          article_slug=excluded.article_slug,full_text=excluded.full_text,
          full_text_html=excluded.full_text_html,image_urls_json=excluded.image_urls_json,
          text_source=excluded.text_source,source_url=excluded.source_url,
          source_database_sha256=excluded.source_database_sha256,
          full_text_sha256=excluded.full_text_sha256,display_prefix_verified=1,
          resolved_at=excluded.resolved_at
        """,
        (
            user_id,
            reply_id,
            article_slug,
            clean_text,
            html,
            json.dumps(image_urls, ensure_ascii=False),
            text_source,
            source_url,
            source_database_sha256,
            hashlib.sha256(clean_text.encode("utf-8")).hexdigest(),
            resolved_at,
        ),
    )
    conn.execute(
        """
        update user_reply_detail_failures set resolved_at=?
        where user_id=? and reply_id=? and resolved_at=''
        """,
        (resolved_at, user_id, reply_id),
    )


def resolve_from_cache(
    conn: sqlite3.Connection, *, canonical_db: Path, user_id: str
) -> dict[str, int]:
    if not canonical_db.exists():
        return {"cache_resolved": 0, "cache_rejected": 0}
    source_sha = hashlib.sha256(canonical_db.read_bytes()).hexdigest()
    source = sqlite3.connect(canonical_db)
    source.row_factory = sqlite3.Row
    canonical: dict[str, list[sqlite3.Row]] = {}
    try:
        for row in source.execute(
            """
            select c.*,coalesce(a.title,'') article_title from comments c
            left join articles a on a.slug=c.article_slug where c.user_id=?
            """,
            (user_id,),
        ):
            canonical.setdefault(row["reply_id"], []).append(row)
    finally:
        source.close()
    resolved = rejected = 0
    feed_rows = conn.execute(
        "select * from user_reply_feed_items where user_id=? order by source_page,position",
        (user_id,),
    ).fetchall()
    with conn:
        for feed in feed_rows:
            matches = canonical.get(feed["reply_id"], [])
            if len(matches) != 1:
                rejected += 1
                continue
            row = matches[0]
            canonical_text = recover_comment_text(row["text"], row["html"])
            if (
                row["user_id"] != user_id
                or row["article_slug"] != feed["article_slug"]
                or row["created_at"] != feed["reply_created_at"]
                or row["username"] != feed["username"]
                or not display_matches_full_text(
                    feed["reply_text"], canonical_text, json.loads(row["image_urls_json"] or "[]")
                )
            ):
                rejected += 1
                continue
            upsert_full_text(
                conn,
                user_id=user_id,
                reply_id=feed["reply_id"],
                article_slug=row["article_slug"],
                text=canonical_text,
                html=row["html"],
                image_urls=json.loads(row["image_urls_json"] or "[]"),
                text_source="canonical-comments-v2",
                source_url=build_reply_detail_url(row["article_slug"], row["reply_id"]),
                source_database_sha256=source_sha,
            )
            resolved += 1
    return {"cache_resolved": resolved, "cache_rejected": rejected}


def hydrate_missing(
    conn: sqlite3.Connection,
    *,
    session: requests.Session,
    user_id: str,
    interval: float,
    timeout: float,
    limit: int,
) -> dict[str, object]:
    rows = conn.execute(
        """
        select f.* from user_reply_feed_items f
        left join user_reply_feed_full_texts t
          on t.user_id=f.user_id and t.reply_id=f.reply_id
         and t.display_prefix_verified=1
        where f.user_id=? and (
          t.reply_id is null
          or (t.text_source='complete-reply-feed-display' and f.displayed_char_count>=100)
          or (
            instr(f.reply_text,?) > 0 and coalesce(t.image_urls_json,'[]')='[]'
            and instr(coalesce(t.full_text,''),'［表情:')=0
            and instr(coalesce(t.full_text,''),'[表情:')=0
          )
        )
        order by f.source_page,f.position
        """,
        (user_id, IMAGE_MARKER),
    ).fetchall()
    if limit > 0:
        rows = rows[:limit]
    succeeded = 0
    failures: Counter[str] = Counter()
    for index, feed in enumerate(rows, start=1):
        try:
            url = build_reply_detail_url(feed["article_slug"], feed["reply_id"])
            html, final_url = request_html(session, url, timeout)
            final_path = urlparse(final_url).path.rstrip("/")
            if final_path in LOGIN_PATHS or any(
                marker in html or marker in final_url for marker in LOGIN_MARKERS
            ):
                raise UserReplyAuthenticationError(
                    "reply_detail_requires_authenticated_cookie"
                )
            if final_path != f"/a/{feed['article_slug']}/{feed['reply_id']}":
                raise UserReplyStructureError(
                    f"reply_detail_unexpected_final_path:{final_path}"
                )
            detail = select_unique_target_reply(
                parse_comments(html, article_slug=feed["article_slug"], page_no=0),
                reply_id=feed["reply_id"],
                expected_user_id=user_id,
            )
            if detail.created_at != feed["reply_created_at"] or detail.username != feed["username"]:
                raise UserReplyStructureError("reply_detail_time_or_username_mismatch")
            if not detail.text and not detail.image_urls:
                raise UserReplyStructureError("reply_detail_content_empty")
            if not display_matches_full_text(
                feed["reply_text"], detail.text, detail.image_urls
            ):
                raise UserReplyStructureError(
                    "reply_detail_author_display_prefix_mismatch"
                )
            if (
                IMAGE_MARKER in feed["reply_text"]
                and not detail.image_urls
                and not contains_face_marker(detail.text)
            ):
                raise UserReplyStructureError("reply_detail_expected_image_missing")
            with conn:
                upsert_full_text(
                    conn,
                    user_id=user_id,
                    reply_id=feed["reply_id"],
                    article_slug=feed["article_slug"],
                    text=detail.text,
                    html=detail.html,
                    image_urls=detail.image_urls,
                    text_source="direct-reply-page-v3",
                    source_url=final_url,
                )
            succeeded += 1
        except Exception as error:
            failures[str(error)] += 1
            with conn:
                conn.execute(
                    """
                    insert into user_reply_detail_failures
                      (user_id,reply_id,article_slug,error_type,error_message,failed_at)
                    values (?,?,?,?,?,?)
                    """,
                    (
                        user_id,
                        feed["reply_id"],
                        feed["article_slug"],
                        type(error).__name__,
                        str(error),
                        utc_now(),
                    ),
                )
            if isinstance(error, UserReplyAuthenticationError):
                raise
        if index == 1 or index % 25 == 0 or index == len(rows):
            print(
                json.dumps(
                    {
                        "stage": "tgb_user_replies_fulltext",
                        "attempted": index,
                        "planned": len(rows),
                        "succeeded": succeeded,
                        "failed": index - succeeded,
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
        if interval > 0 and index < len(rows):
            time.sleep(interval)
    return {
        "hydrate_planned": len(rows),
        "hydrate_succeeded": succeeded,
        "hydrate_failed": len(rows) - succeeded,
        "failure_reasons": dict(failures.most_common(20)),
    }


def status(conn: sqlite3.Connection, user_id: str) -> dict[str, object]:
    feed = int(
        conn.execute(
            "select count(*) from user_reply_feed_items where user_id=?", (user_id,)
        ).fetchone()[0]
    )
    full = int(
        conn.execute(
            """
            select count(*) from user_reply_feed_full_texts
            where user_id=? and display_prefix_verified=1
            """,
            (user_id,),
        ).fetchone()[0]
    )
    sources = {
        row[0]: int(row[1])
        for row in conn.execute(
            """
            select text_source,count(*) from user_reply_feed_full_texts
            where user_id=? and display_prefix_verified=1 group by text_source
            """,
            (user_id,),
        )
    }
    unresolved_failure_ids = int(
        conn.execute(
            """
            select count(distinct reply_id) from user_reply_detail_failures
            where user_id=? and resolved_at=''
            """,
            (user_id,),
        ).fetchone()[0]
    )
    image_marked = int(
        conn.execute(
            "select count(*) from user_reply_feed_items where user_id=? and instr(reply_text,?)>0",
            (user_id, IMAGE_MARKER),
        ).fetchone()[0]
    )
    image_hydrated = int(
        conn.execute(
            """
            select count(*) from user_reply_feed_items f
            join user_reply_feed_full_texts t
              on t.user_id=f.user_id and t.reply_id=f.reply_id
             and t.display_prefix_verified=1
            where f.user_id=? and instr(f.reply_text,?)>0
              and coalesce(t.image_urls_json,'[]')<>'[]'
            """,
            (user_id, IMAGE_MARKER),
        ).fetchone()[0]
    )
    image_face_only = int(
        conn.execute(
            """
            select count(*) from user_reply_feed_items f
            join user_reply_feed_full_texts t
              on t.user_id=f.user_id and t.reply_id=f.reply_id
             and t.display_prefix_verified=1
            where f.user_id=? and instr(f.reply_text,?)>0
              and coalesce(t.image_urls_json,'[]')='[]'
              and (instr(t.full_text,'［表情:')>0 or instr(t.full_text,'[表情:')>0)
            """,
            (user_id, IMAGE_MARKER),
        ).fetchone()[0]
    )
    image_resolved = image_hydrated + image_face_only
    capped_displays, previously_verified = conn.execute(
        """
        select count(*), count(case when t.display_prefix_verified=1 then 1 end)
        from user_reply_feed_items f
        join user_reply_feed_full_texts t using(user_id,reply_id)
        where f.user_id=? and t.text_source='complete-reply-feed-display'
          and f.displayed_char_count>=100
        """, (user_id,),
    ).fetchone()
    verified_full = full - previously_verified
    full_text_complete = bool(feed > 0 and feed == verified_full)
    return {
        "feed_records": feed,
        "full_text_records": verified_full,
        "unresolved": feed - verified_full,
        "unverified_capped_displays": capped_displays,
        "source_counts": sources,
        "unresolved_failure_ids": unresolved_failure_ids,
        "full_text_complete": full_text_complete,
        "image_marked_feed_records": image_marked,
        "image_hydrated_records": image_hydrated,
        "image_face_only_records": image_face_only,
        "image_unresolved_records": image_marked - image_resolved,
        "full_hydration_complete": bool(
            full_text_complete and image_marked == image_resolved
        ),
    }


def sanitize_existing_full_texts(conn: sqlite3.Connection, user_id: str) -> int:
    """Apply the provider's marker-removal contract to resumable older rows."""

    changed = 0
    with conn:
        for row in conn.execute(
            """
            select reply_id,full_text from user_reply_feed_full_texts
            where user_id=? and display_prefix_verified=1
            """,
            (user_id,),
        ).fetchall():
            clean_text = clean_author_full_text(row["full_text"])
            if clean_text == row["full_text"]:
                continue
            conn.execute(
                """
                update user_reply_feed_full_texts
                set full_text=?,full_text_sha256=?,resolved_at=?
                where user_id=? and reply_id=?
                """,
                (
                    clean_text,
                    hashlib.sha256(clean_text.encode("utf-8")).hexdigest(),
                    utc_now(),
                    user_id,
                    row["reply_id"],
                ),
            )
            changed += 1
    return changed


def resolve_complete_feed_displays(conn: sqlite3.Connection, user_id: str) -> int:
    """Promote only demonstrably untruncated author-only feed displays.

    This is a terminal fallback for deleted/unlocatable reply details.  The
    source-reported total character count must be no larger than the stored
    target-author segment; otherwise a 100/140-character preview is never
    represented as full text.
    """

    rows = conn.execute(
        """
        select f.* from user_reply_feed_items f
        left join user_reply_feed_full_texts t
          on t.user_id=f.user_id and t.reply_id=f.reply_id
         and t.display_prefix_verified=1
        where f.user_id=? and t.reply_id is null
          and f.displayed_char_count is not null
          and f.displayed_char_count < 100
          and f.displayed_char_count <= length(f.reply_text)
          and trim(f.reply_text) <> ''
        order by f.source_page,f.position
        """,
        (user_id,),
    ).fetchall()
    with conn:
        for row in rows:
            upsert_full_text(
                conn,
                user_id=user_id,
                reply_id=row["reply_id"],
                article_slug=row["article_slug"],
                text=row["reply_text"],
                html="",
                image_urls=[],
                text_source="complete-reply-feed-display",
                source_url=row["reply_url"],
            )
    return len(rows)


def run(args: argparse.Namespace) -> dict[str, object]:
    load_env_file()
    cookie = os.getenv("COOKIE", "").strip()
    if not cookie:
        raise UserReplyAuthenticationError("reply_feed_cookie_missing")
    db_path = Path(args.db).expanduser().resolve()
    summary_path = Path(args.summary).expanduser().resolve()
    canonical_db = Path(args.canonical_db).expanduser().resolve()
    conn = connect_db(db_path)
    baseline_reply_ids = known_reply_ids(conn, args.user_id)
    baseline_records = len(baseline_reply_ids)
    session = requests.Session()
    session.headers.update(
        {
            "Cookie": cookie,
            "User-Agent": os.getenv("USER_AGENT", "Mozilla/5.0"),
            "Referer": f"https://www.tgb.cn/blog/{args.user_id}",
        }
    )
    try:
        first_url = build_user_reply_feed_url(args.user_id, args.anchor_date, 1)
        first_html, first_final = request_html(session, first_url, args.timeout)
        first_records = parse_user_reply_feed(
            first_html, user_id=args.user_id, source_page=1
        )
        validate_feed_page(
            final_url=first_final,
            html=first_html,
            records=first_records,
            expected_user_id=args.user_id,
            expected_username=args.expected_username,
            expected_page_no=1,
        )
        total_pages = parse_feed_total_pages(
            first_html, final_url=first_final, expected_user_id=args.user_id
        )
        end_page = min(args.end_page or total_pages, total_pages)
        planned = list(range(1, end_page + 1))
        if args.max_pages > 0:
            planned = planned[: args.max_pages]
        scanned_pages: list[int] = []
        known_reply_streak = 0
        incremental_new_ids: set[str] = set()
        stop_reason = ""
        boundary_closed = False
        for page_no in planned:
            if page_no == 1:
                html, final_url, records, page_url = (
                    first_html,
                    first_final,
                    first_records,
                    first_url,
                )
            else:
                page_url = build_user_reply_feed_url(
                    args.user_id, args.anchor_date, page_no
                )
                html, final_url = request_html(session, page_url, args.timeout)
                records = parse_user_reply_feed(
                    html, user_id=args.user_id, source_page=page_no
                )
                validate_feed_page(
                    final_url=final_url,
                    html=html,
                    records=records,
                    expected_user_id=args.user_id,
                    expected_username=args.expected_username,
                    expected_page_no=page_no,
                )
                if parse_feed_total_pages(
                    html, final_url=final_url, expected_user_id=args.user_id
                ) != total_pages:
                    raise UserReplyStructureError("reply_feed_total_page_drift")
            store_page(
                conn,
                user_id=args.user_id,
                anchor_date=args.anchor_date,
                page_no=page_no,
                page_url=page_url,
                final_url=final_url,
                html=html,
                records=records,
                total_pages=total_pages,
            )
            scanned_pages.append(page_no)
            if args.incremental and baseline_reply_ids:
                known_reply_streak, page_new_ids = advance_known_reply_streak(
                    records,
                    baseline_reply_ids=baseline_reply_ids,
                    current_streak=known_reply_streak,
                )
                incremental_new_ids.update(page_new_ids)
                if known_reply_streak >= args.known_reply_threshold:
                    stop_reason = "known_reply_threshold"
                    boundary_closed = True
                    break
            if args.interval > 0 and page_no != planned[-1]:
                time.sleep(args.interval)
        capture_complete = len(scanned_pages) == total_pages
        if capture_complete:
            stop_reason = "all_pages"
            boundary_closed = True
        elif not stop_reason:
            stop_reason = "page_limit_before_known_boundary"

        canonical_ready = bool(capture_complete or (args.incremental and boundary_closed))
        merge_stats: dict[str, object] = {
            "records_seen": 0,
            "unique_records": 0,
            "duplicate_occurrences": 0,
            "new_records": 0,
            "new_reply_ids": [],
            "updated_records": 0,
            "updated_reply_ids": [],
            "unchanged_records": 0,
            "current_records": baseline_records,
        }
        if args.incremental and baseline_reply_ids and canonical_ready:
            merge_stats = merge_incremental_feed(
                conn,
                user_id=args.user_id,
                anchor_date=args.anchor_date,
                scanned_pages=len(scanned_pages),
            )
        if capture_complete:
            full_stats = finalize_feed(
                conn,
                user_id=args.user_id,
                anchor_date=args.anchor_date,
                total_pages=total_pages,
            )
            feed_stats = {**full_stats, **merge_stats}
            feed_stats.update(full_stats)
            feed_stats["current_records"] = int(
                conn.execute(
                    "select count(*) from user_reply_feed_items where user_id=?",
                    (args.user_id,),
                ).fetchone()[0]
            )
        elif canonical_ready:
            feed_stats = merge_stats
        else:
            feed_stats = merge_stats

        if args.incremental:
            record_incremental_receipt(
                conn,
                user_id=args.user_id,
                anchor_date=args.anchor_date,
                total_pages=total_pages,
                scanned_pages=len(scanned_pages),
                baseline_records=baseline_records,
                merge_stats=feed_stats,
                stop_reason=stop_reason,
                boundary_closed=boundary_closed,
            )
        resolution: dict[str, object] = {
            "mode": args.text_mode,
            "cache_resolved": 0,
            "cache_rejected": 0,
            "hydrate_planned": 0,
            "hydrate_succeeded": 0,
            "hydrate_failed": 0,
        }
        if canonical_ready and args.text_mode in {"full-cache", "full-hydrate"}:
            resolution.update(
                resolve_from_cache(
                    conn, canonical_db=canonical_db, user_id=args.user_id
                )
            )
        resolution["complete_feed_displays_resolved"] = resolve_complete_feed_displays(
            conn, args.user_id
        )
        if canonical_ready and args.text_mode == "full-hydrate":
            resolution.update(
                hydrate_missing(
                    conn,
                    session=session,
                    user_id=args.user_id,
                    interval=args.interval,
                    timeout=args.timeout,
                    limit=args.hydrate_limit,
                )
            )
        resolution["existing_full_texts_sanitized"] = sanitize_existing_full_texts(
            conn, args.user_id
        )
        current = status(conn, args.user_id)
        summary = {
            "schema_version": "1.1.0-tgb-user-reply-archive",
            "endpoint": "/user/blog/moreReplyMod",
            "points_consuming_endpoint_used": False,
            "user_id": args.user_id,
            "expected_username": args.expected_username,
            "anchor_date": args.anchor_date,
            "coverage": {
                "total_pages": total_pages,
                "captured_pages": len(scanned_pages),
                "complete": capture_complete,
                "scan_mode": "incremental" if args.incremental else "full",
                "baseline_records": baseline_records,
                "known_reply_threshold": args.known_reply_threshold,
                "known_reply_streak": known_reply_streak,
                "new_ids_seen_while_scanning": len(incremental_new_ids),
                "stop_reason": stop_reason,
                "incremental_boundary_closed": boundary_closed,
                **feed_stats,
            },
            "content_boundary": {
                "feed_stores_target_author_segment_only": True,
                "third_party_quote_body_persisted": False,
                "raw_page_body_persisted": False,
            },
            "resolution": {**resolution, **current},
            "sqlite_integrity": conn.execute("pragma integrity_check").fetchone()[0],
            "green": bool(
                canonical_ready
                and current["feed_records"] > 0
                and (
                    args.text_mode == "display"
                    or (
                        args.text_mode == "full-hydrate"
                        and current["full_hydration_complete"]
                    )
                    or (
                        args.text_mode == "full-cache"
                        and current["full_text_complete"]
                    )
                )
            ),
            "retrieved_at": utc_now(),
        }
    finally:
        session.close()
        conn.close()
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="抓取指定淘股吧用户全部回帖目录，并可选择性解析作者全文"
    )
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--expected-username", required=True)
    parser.add_argument("--anchor-date", default=date.today().isoformat())
    parser.add_argument("--db", default="")
    parser.add_argument("--summary", default="")
    parser.add_argument("--canonical-db", default="")
    parser.add_argument(
        "--text-mode", choices=("display", "full-cache", "full-hydrate"), default="display"
    )
    parser.add_argument("--max-pages", type=int, default=0)
    parser.add_argument("--end-page", type=int, default=0)
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="从第1页向后扫描，连续遇到已知reply_id后合并新增项并停止",
    )
    parser.add_argument(
        "--known-reply-threshold",
        type=int,
        default=20,
        help="增量模式达到多少个连续已知reply_id后闭合水位",
    )
    parser.add_argument("--hydrate-limit", type=int, default=0)
    parser.add_argument("--interval", type=float, default=0.5)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--manual-approval", action="store_true")
    args = parser.parse_args()
    if args.text_mode == "full-hydrate" and not args.manual_approval:
        parser.error("--text-mode full-hydrate requires --manual-approval")
    if args.known_reply_threshold < 1:
        parser.error("--known-reply-threshold must be positive")
    args.db = args.db or str(
        PROJECT_ROOT / "data" / f"tgb-user-{args.user_id}-reply-feed.sqlite"
    )
    args.summary = args.summary or str(
        PROJECT_ROOT / "data" / f"tgb-user-{args.user_id}-reply-feed-summary.json"
    )
    args.canonical_db = args.canonical_db or str(
        PROJECT_ROOT / "data" / f"tgb-user-{args.user_id}.sqlite"
    )
    return args


if __name__ == "__main__":
    run(parse_args())
