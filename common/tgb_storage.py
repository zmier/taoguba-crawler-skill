from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Iterable

from common.tgb_article import ArticleDetail
from common.tgb_comment import CommentRecord
from common.tgb_index import BbsIndexRecord


def connect_db(path: str | Path) -> sqlite3.Connection:
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("pragma foreign_keys = on")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        create table if not exists articles (
            slug text primary key,
            url text not null,
            title text not null default '',
            author text not null default '',
            author_id text not null default '',
            reply_count integer not null default 0,
            view_count integer not null default 0,
            last_reply_time text not null default '',
            post_time text not null default '',
            source_page integer not null default 0,
            source_url text not null default '',
            topic_id text not null default '',
            comment_count integer not null default 0,
            comment_page_count integer not null default 0,
            main_text text not null default '',
            main_html text not null default '',
            image_urls_json text not null default '[]',
            fetched_at text not null default '',
            created_at text not null,
            updated_at text not null
        );

        create table if not exists article_pages (
            article_slug text not null,
            page_no integer not null,
            url text not null,
            html_sha256 text not null default '',
            fetched_at text not null default '',
            primary key (article_slug, page_no),
            foreign key (article_slug) references articles(slug) on delete cascade
        );

        create table if not exists comments (
            article_slug text not null,
            page_no integer not null,
            reply_id text not null,
            user_id text not null default '',
            username text not null default '',
            is_author integer not null default 0,
            floor_label text not null default '',
            created_at text not null default '',
            text text not null default '',
            html text not null default '',
            image_urls_json text not null default '[]',
            stored_at text not null,
            primary key (article_slug, reply_id)
        );

        create table if not exists crawl_queue (
            url text primary key,
            kind text not null,
            status text not null default 'pending',
            priority integer not null default 0,
            attempts integer not null default 0,
            last_error text not null default '',
            next_run_at text,
            created_at text not null,
            updated_at text not null
        );

        create table if not exists failures (
            id integer primary key autoincrement,
            url text not null,
            kind text not null,
            error text not null,
            attempts integer not null,
            created_at text not null
        );
        """
    )
    conn.commit()


def upsert_index_records(conn: sqlite3.Connection, records: Iterable[BbsIndexRecord]) -> int:
    now = _now()
    rows = list(records)
    conn.executemany(
        """
        insert into articles (
            slug, url, title, author, author_id, reply_count, view_count,
            last_reply_time, post_time, source_page, source_url, created_at, updated_at
        )
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        on conflict(slug) do update set
            url = excluded.url,
            title = excluded.title,
            author = excluded.author,
            author_id = excluded.author_id,
            reply_count = excluded.reply_count,
            view_count = excluded.view_count,
            last_reply_time = excluded.last_reply_time,
            post_time = excluded.post_time,
            source_page = excluded.source_page,
            source_url = excluded.source_url,
            updated_at = excluded.updated_at
        """,
        [
            (
                item.slug,
                item.url,
                item.title,
                item.author,
                item.author_id,
                item.reply_count,
                item.view_count,
                item.last_reply_time,
                item.post_time,
                item.source_page,
                item.source_url,
                now,
                now,
            )
            for item in rows
        ],
    )
    conn.commit()
    return len(rows)


def upsert_article_detail(conn: sqlite3.Connection, detail: ArticleDetail) -> None:
    now = _now()
    conn.execute(
        """
        insert into articles (
            slug, url, title, author, author_id, view_count, topic_id,
            comment_count, comment_page_count, main_text, main_html,
            image_urls_json, fetched_at, created_at, updated_at
        )
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        on conflict(slug) do update set
            url = excluded.url,
            title = excluded.title,
            author = excluded.author,
            author_id = excluded.author_id,
            view_count = excluded.view_count,
            topic_id = excluded.topic_id,
            comment_count = excluded.comment_count,
            comment_page_count = excluded.comment_page_count,
            main_text = excluded.main_text,
            main_html = excluded.main_html,
            image_urls_json = excluded.image_urls_json,
            fetched_at = excluded.fetched_at,
            updated_at = excluded.updated_at
        """,
        (
            detail.slug,
            detail.url,
            detail.title,
            detail.author,
            detail.author_id,
            detail.view_count,
            detail.topic_id,
            detail.comment_count,
            detail.comment_page_count,
            detail.main_text,
            detail.main_html,
            _json(detail.image_urls),
            now,
            now,
            now,
        ),
    )
    conn.commit()


def upsert_comments(conn: sqlite3.Connection, comments: Iterable[CommentRecord]) -> int:
    now = _now()
    rows = list(comments)
    conn.executemany(
        """
        insert into comments (
            article_slug, page_no, reply_id, user_id, username, is_author,
            floor_label, created_at, text, html, image_urls_json, stored_at
        )
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        on conflict(article_slug, reply_id) do update set
            page_no = excluded.page_no,
            user_id = excluded.user_id,
            username = excluded.username,
            is_author = excluded.is_author,
            floor_label = excluded.floor_label,
            created_at = excluded.created_at,
            text = excluded.text,
            html = excluded.html,
            image_urls_json = excluded.image_urls_json,
            stored_at = excluded.stored_at
        """,
        [
            (
                item.article_slug,
                item.page_no,
                item.reply_id,
                item.user_id,
                item.username,
                1 if item.is_author else 0,
                item.floor_label,
                item.created_at,
                item.text,
                item.html,
                _json(item.image_urls),
                now,
            )
            for item in rows
        ],
    )
    conn.commit()
    return len(rows)


def upsert_article_page(
    conn: sqlite3.Connection,
    article_slug: str,
    page_no: int,
    url: str,
    html: str,
    fetched_at: str | None = None,
) -> None:
    timestamp = fetched_at or _now()
    conn.execute(
        """
        insert into article_pages (article_slug, page_no, url, html_sha256, fetched_at)
        values (?, ?, ?, ?, ?)
        on conflict(article_slug, page_no) do update set
            url = excluded.url,
            html_sha256 = excluded.html_sha256,
            fetched_at = excluded.fetched_at
        """,
        (article_slug, page_no, url, hashlib.sha256(html.encode("utf-8")).hexdigest(), timestamp),
    )
    conn.commit()


def get_article(conn: sqlite3.Connection, slug: str) -> sqlite3.Row:
    return conn.execute("select * from articles where slug = ?", (slug,)).fetchone()


def count_rows(conn: sqlite3.Connection, table: str) -> int:
    if table not in {"articles", "article_pages", "comments", "crawl_queue", "failures"}:
        raise ValueError(f"unsupported table: {table}")
    return int(conn.execute(f"select count(*) from {table}").fetchone()[0])


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _json(value: list[str]) -> str:
    return json.dumps(value, ensure_ascii=False)
