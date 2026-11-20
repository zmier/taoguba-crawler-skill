#!/usr/bin/env python3
"""Archive one target author's main-post and reply images as Base64 in SQLite.

The source text database is opened read-only. Image bytes are written to a
separate content-addressed SQLite database so media backfill does not change
text/source hashes. Third-party comment images are explicitly excluded.
"""

from __future__ import annotations

import argparse
import base64
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import time
from urllib.parse import urlparse

import requests


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ALLOWED_SOURCE_HOSTS = {
    "image.tgb.cn",
    # Historical first-party hosts still embedded in 2011-2014 posts/replies.
    "www.taoguba.net",
    "www.taoguba.com.cn",
    "img.taoguba.com.cn",
}
ALLOWED_FINAL_HOSTS = ALLOWED_SOURCE_HOSTS | {
    "www.tgb.cn",
    "image.taoguba.com.cn",
}
LEGACY_IMAGE_HOSTS = {
    "www.taoguba.net",
    "www.taoguba.com.cn",
    "img.taoguba.com.cn",
}


class ImageInventoryError(RuntimeError):
    """The canonical image inventory is missing or structurally invalid."""


class ImageDownloadError(RuntimeError):
    """A response cannot be accepted as an archived image asset."""


@dataclass(frozen=True)
class ContentImageLink:
    author_id: str
    article_slug: str
    content_kind: str
    reply_id: str
    position: int
    source_url: str


@dataclass(frozen=True)
class DownloadedImage:
    source_url: str
    final_url: str
    http_status: int
    mime_type: str
    content: bytes
    content_sha256: str
    base64_data: str
    etag: str
    last_modified: str


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def display_path(path: Path, *, base: Path = PROJECT_ROOT) -> str:
    for candidate in (base, Path.cwd().resolve()):
        try:
            return str(path.relative_to(candidate))
        except ValueError:
            continue
    return str(path)


def _read_image_urls(raw: str, *, identity: str) -> list[str]:
    try:
        values = json.loads(raw or "[]")
    except json.JSONDecodeError as error:
        raise ImageInventoryError(f"invalid_image_urls_json:{identity}") from error
    if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
        raise ImageInventoryError(f"image_urls_must_be_string_list:{identity}")
    urls: list[str] = []
    for value in values:
        url = value.strip()
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or parsed.netloc not in ALLOWED_SOURCE_HOSTS:
            raise ImageInventoryError(f"image_url_not_allowed:{identity}:{parsed.netloc}")
        urls.append(url)
    return urls


def load_content_image_links(
    canonical_db: Path,
    *,
    author_id: str,
    reply_feed_db: Path | None = None,
) -> list[ContentImageLink]:
    """Read target-author image references from canonical and reply-feed DBs.

    The canonical database owns main posts and replies beneath those posts.  An
    optional user-reply-feed database adds the same author's replies beneath
    other users' posts.  Duplicate identities must agree on the source URL;
    conflicting databases fail closed instead of silently choosing one.
    """

    if not canonical_db.exists():
        raise ImageInventoryError(f"canonical_db_missing:{canonical_db}")
    uri = f"file:{canonical_db}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        integrity = conn.execute("pragma integrity_check").fetchone()[0]
        if integrity != "ok":
            raise ImageInventoryError(f"canonical_integrity:{integrity}")
        links: list[ContentImageLink] = []
        article_columns = {
            row[1] for row in conn.execute("pragma table_info(articles)").fetchall()
        }
        article_filter = "where author_id = ?" if "author_id" in article_columns else ""
        article_params = (author_id,) if article_filter else ()
        for row in conn.execute(
            f"""
            select slug, image_urls_json
            from articles
            {article_filter}
            order by source_page, slug
            """,
            article_params,
        ).fetchall():
            urls = _read_image_urls(
                row["image_urls_json"], identity=f"article:{row['slug']}"
            )
            links.extend(
                ContentImageLink(
                    author_id=author_id,
                    article_slug=row["slug"],
                    content_kind="main_post",
                    reply_id="",
                    position=position,
                    source_url=url,
                )
                for position, url in enumerate(urls, start=1)
            )
        reply_sql = """
            select c.article_slug, c.reply_id, c.image_urls_json
            from comments c
            join articles a on a.slug = c.article_slug
            where c.user_id = ?
        """
        reply_params: tuple[str, ...] = (author_id,)
        if "author_id" in article_columns:
            reply_sql += " and a.author_id = ?"
            reply_params = (author_id, author_id)
        reply_sql += " order by c.article_slug, c.page_no, c.reply_id"
        for row in conn.execute(reply_sql, reply_params).fetchall():
            urls = _read_image_urls(
                row["image_urls_json"],
                identity=f"reply:{row['article_slug']}:{row['reply_id']}",
            )
            links.extend(
                ContentImageLink(
                    author_id=author_id,
                    article_slug=row["article_slug"],
                    content_kind="author_reply",
                    reply_id=row["reply_id"],
                    position=position,
                    source_url=url,
                )
                for position, url in enumerate(urls, start=1)
            )
    finally:
        conn.close()

    if reply_feed_db is not None:
        links.extend(load_reply_feed_image_links(reply_feed_db, author_id=author_id))

    deduplicated: dict[tuple[str, str, str, str, int], ContentImageLink] = {}
    for link in links:
        identity = (
            link.author_id,
            link.article_slug,
            link.content_kind,
            link.reply_id,
            link.position,
        )
        previous = deduplicated.get(identity)
        if previous is not None and previous.source_url != link.source_url:
            raise ImageInventoryError(
                "conflicting_image_link_identity:"
                f"{link.article_slug}:{link.reply_id}:{link.position}"
            )
        deduplicated[identity] = link
    return list(deduplicated.values())


def load_reply_feed_image_links(
    reply_feed_db: Path,
    *,
    author_id: str,
) -> list[ContentImageLink]:
    """Read verified target-author reply images from a user-reply-feed DB."""

    if not reply_feed_db.exists():
        raise ImageInventoryError(f"reply_feed_db_missing:{reply_feed_db}")
    uri = f"file:{reply_feed_db}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        integrity = conn.execute("pragma integrity_check").fetchone()[0]
        if integrity != "ok":
            raise ImageInventoryError(f"reply_feed_integrity:{integrity}")
        tables = {
            row[0]
            for row in conn.execute(
                "select name from sqlite_master where type='table'"
            ).fetchall()
        }
        if "user_reply_feed_full_texts" not in tables:
            raise ImageInventoryError("reply_feed_full_text_table_missing")
        links: list[ContentImageLink] = []
        for row in conn.execute(
            """
            select article_slug, reply_id, image_urls_json
            from user_reply_feed_full_texts
            where user_id = ? and display_prefix_verified = 1
            order by article_slug, reply_id
            """,
            (author_id,),
        ).fetchall():
            urls = _read_image_urls(
                row["image_urls_json"],
                identity=f"reply-feed:{row['article_slug']}:{row['reply_id']}",
            )
            links.extend(
                ContentImageLink(
                    author_id=author_id,
                    article_slug=row["article_slug"],
                    content_kind="author_reply",
                    reply_id=row["reply_id"],
                    position=position,
                    source_url=url,
                )
                for position, url in enumerate(urls, start=1)
            )
        return links
    finally:
        conn.close()


def connect_media_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("pragma journal_mode = wal")
    conn.execute("pragma foreign_keys = on")
    ensure_media_tables(conn)
    return conn


def ensure_media_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        create table if not exists image_assets (
            content_sha256 text primary key,
            mime_type text not null,
            byte_size integer not null,
            base64_data text not null,
            base64_char_count integer not null,
            verified_at text not null
        );

        create table if not exists image_sources (
            source_url text primary key,
            final_url text not null default '',
            content_sha256 text,
            http_status integer,
            content_type text not null default '',
            etag text not null default '',
            last_modified text not null default '',
            status text not null,
            downloaded_at text not null default '',
            foreign key (content_sha256) references image_assets(content_sha256)
        );

        create table if not exists content_image_links (
            author_id text not null,
            article_slug text not null,
            content_kind text not null check(content_kind in ('main_post', 'author_reply')),
            reply_id text not null default '',
            position integer not null,
            source_url text not null,
            content_sha256 text,
            inventoried_at text not null,
            primary key (author_id, article_slug, content_kind, reply_id, position),
            foreign key (source_url) references image_sources(source_url),
            foreign key (content_sha256) references image_assets(content_sha256)
        );

        create table if not exists image_inventory_receipts (
            author_id text primary key,
            canonical_database text not null,
            canonical_database_sha256 text not null,
            reply_feed_database text not null default '',
            reply_feed_database_sha256 text not null default '',
            main_post_links integer not null,
            author_reply_links integer not null,
            unique_source_urls integer not null,
            inventoried_at text not null
        );

        create table if not exists image_download_failures (
            id integer primary key autoincrement,
            source_url text not null,
            error_type text not null,
            error_message text not null,
            failed_at text not null,
            resolved_at text not null default ''
        );
        """
    )
    receipt_columns = {
        row[1]
        for row in conn.execute("pragma table_info(image_inventory_receipts)").fetchall()
    }
    if "reply_feed_database" not in receipt_columns:
        conn.execute(
            "alter table image_inventory_receipts "
            "add column reply_feed_database text not null default ''"
        )
    if "reply_feed_database_sha256" not in receipt_columns:
        conn.execute(
            "alter table image_inventory_receipts "
            "add column reply_feed_database_sha256 text not null default ''"
        )
    # Failure state is source-URL scoped. Older retries could leave multiple
    # unresolved rows for one URL; retain only the latest attempt as current.
    conn.execute(
        """
        update image_download_failures set resolved_at = ?
        where resolved_at = '' and id not in (
          select max(id) from image_download_failures
          where resolved_at = '' group by source_url
        )
        """,
        (utc_now(),),
    )
    conn.execute(
        """
        update image_sources set status = 'error'
        where status = 'pending' and exists (
          select 1 from image_download_failures f
          where f.source_url = image_sources.source_url and f.resolved_at = ''
        )
        """
    )
    conn.commit()


def sync_inventory(
    conn: sqlite3.Connection,
    *,
    links: list[ContentImageLink],
    canonical_db: Path,
    canonical_sha256: str,
    reply_feed_db: Path | None,
    reply_feed_sha256: str,
    author_id: str,
) -> dict[str, int]:
    unique_urls = sorted({link.source_url for link in links})
    inventoried_at = utc_now()
    with conn:
        conn.executemany(
            """
            insert into image_sources (source_url, status)
            values (?, 'pending')
            on conflict(source_url) do nothing
            """,
            [(url,) for url in unique_urls],
        )
        conn.execute(
            "delete from content_image_links where author_id = ?",
            (author_id,),
        )
        conn.executemany(
            """
            insert into content_image_links (
                author_id, article_slug, content_kind, reply_id, position,
                source_url, content_sha256, inventoried_at
            ) values (?, ?, ?, ?, ?, ?,
                (select content_sha256 from image_sources where source_url = ?
                 and status = 'downloaded'), ?)
            """,
            [
                (
                    link.author_id,
                    link.article_slug,
                    link.content_kind,
                    link.reply_id,
                    link.position,
                    link.source_url,
                    link.source_url,
                    inventoried_at,
                )
                for link in links
            ],
        )
        placeholders = ",".join("?" for _ in unique_urls)
        if unique_urls:
            conn.execute(
                f"delete from image_sources where source_url not in ({placeholders})",
                unique_urls,
            )
        else:
            conn.execute("delete from image_sources")
        conn.execute(
            """
            delete from image_assets
            where content_sha256 not in (
                select content_sha256 from image_sources
                where content_sha256 is not null
            )
            """
        )
        conn.execute(
            """
            insert into image_inventory_receipts (
                author_id, canonical_database, canonical_database_sha256,
                reply_feed_database, reply_feed_database_sha256,
                main_post_links, author_reply_links, unique_source_urls,
                inventoried_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(author_id) do update set
                canonical_database = excluded.canonical_database,
                canonical_database_sha256 = excluded.canonical_database_sha256,
                reply_feed_database = excluded.reply_feed_database,
                reply_feed_database_sha256 = excluded.reply_feed_database_sha256,
                main_post_links = excluded.main_post_links,
                author_reply_links = excluded.author_reply_links,
                unique_source_urls = excluded.unique_source_urls,
                inventoried_at = excluded.inventoried_at
            """,
            (
                author_id,
                display_path(canonical_db),
                canonical_sha256,
                display_path(reply_feed_db) if reply_feed_db is not None else "",
                reply_feed_sha256,
                sum(link.content_kind == "main_post" for link in links),
                sum(link.content_kind == "author_reply" for link in links),
                len(unique_urls),
                inventoried_at,
            ),
        )
    return {
        "main_post_links": sum(link.content_kind == "main_post" for link in links),
        "author_reply_links": sum(
            link.content_kind == "author_reply" for link in links
        ),
        "unique_source_urls": len(unique_urls),
    }


def _sniff_image_mime(content: bytes) -> str:
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        return "image/webp"
    if content.startswith(b"BM"):
        return "image/bmp"
    prefix = content[:512].lstrip().lower()
    if prefix.startswith(b"<svg") or (prefix.startswith(b"<?xml") and b"<svg" in prefix):
        return "image/svg+xml"
    return ""


def build_image_candidate_urls(source_url: str) -> list[str]:
    """Return bounded first-party fallbacks for historical TGB image URLs."""

    parsed = urlparse(source_url)
    candidates = [source_url]
    if parsed.netloc in LEGACY_IMAGE_HOSTS:
        candidates.append(f"https://image.tgb.cn{parsed.path}_760w.png")
    elif parsed.netloc == "image.tgb.cn" and parsed.path.endswith("_760w.png"):
        original_path = parsed.path[: -len("_760w.png")]
        candidates.extend(
            [
                f"https://image.tgb.cn{original_path}_max.png",
                f"https://image.tgb.cn{original_path}",
            ]
        )
    return list(dict.fromkeys(candidates))


def _download_image_candidate(
    session: requests.Session,
    candidate_url: str,
    *,
    source_url: str,
    timeout: float,
    max_bytes: int,
) -> DownloadedImage:
    response = session.get(candidate_url, timeout=timeout, stream=True)
    try:
        response.raise_for_status()
        final = urlparse(response.url)
        if final.scheme not in {"http", "https"} or final.netloc not in ALLOWED_FINAL_HOSTS:
            raise ImageDownloadError(f"image_redirect_not_allowed:{final.netloc}")
        declared_length = response.headers.get("Content-Length", "").strip()
        if declared_length.isdigit() and int(declared_length) > max_bytes:
            raise ImageDownloadError(
                f"image_too_large_declared:{declared_length}>{max_bytes}"
            )
        chunks: list[bytes] = []
        received = 0
        for chunk in response.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            received += len(chunk)
            if received > max_bytes:
                raise ImageDownloadError(
                    f"image_too_large_streamed:{received}>{max_bytes}"
                )
            chunks.append(chunk)
    finally:
        response.close()
    content = b"".join(chunks)
    if not content:
        raise ImageDownloadError("image_body_empty")
    header_mime = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
    sniffed_mime = _sniff_image_mime(content)
    if not sniffed_mime:
        raise ImageDownloadError(f"unsupported_image_signature:{header_mime or 'missing'}")
    if header_mime.startswith("image/") and header_mime != sniffed_mime:
        # Several servers return image/jpg for JPEG; normalize that alias.
        if not (header_mime == "image/jpg" and sniffed_mime == "image/jpeg"):
            raise ImageDownloadError(
                f"image_mime_signature_mismatch:{header_mime}!={sniffed_mime}"
            )
    encoded = base64.b64encode(content).decode("ascii")
    if base64.b64decode(encoded, validate=True) != content:
        raise ImageDownloadError("base64_roundtrip_failed")
    return DownloadedImage(
        source_url=source_url,
        final_url=response.url,
        http_status=response.status_code,
        mime_type=sniffed_mime,
        content=content,
        content_sha256=hashlib.sha256(content).hexdigest(),
        base64_data=encoded,
        etag=response.headers.get("ETag", ""),
        last_modified=response.headers.get("Last-Modified", ""),
    )


def download_image(
    session: requests.Session,
    source_url: str,
    *,
    timeout: float,
    max_bytes: int,
) -> DownloadedImage:
    failures: list[str] = []
    for candidate in build_image_candidate_urls(source_url):
        try:
            return _download_image_candidate(
                session,
                candidate,
                source_url=source_url,
                timeout=timeout,
                max_bytes=max_bytes,
            )
        except Exception as error:
            response = getattr(error, "response", None)
            status = getattr(response, "status_code", "")
            suffix = f":{status}" if status else ""
            failures.append(
                f"{urlparse(candidate).netloc}:{type(error).__name__}{suffix}"
            )
    raise ImageDownloadError("all_image_candidates_failed:" + ",".join(failures))


def _store_download(conn: sqlite3.Connection, image: DownloadedImage) -> None:
    stored_at = utc_now()
    with conn:
        conn.execute(
            """
            insert into image_assets (
                content_sha256, mime_type, byte_size, base64_data,
                base64_char_count, verified_at
            ) values (?, ?, ?, ?, ?, ?)
            on conflict(content_sha256) do update set
                mime_type = excluded.mime_type,
                byte_size = excluded.byte_size,
                base64_data = excluded.base64_data,
                base64_char_count = excluded.base64_char_count,
                verified_at = excluded.verified_at
            """,
            (
                image.content_sha256,
                image.mime_type,
                len(image.content),
                image.base64_data,
                len(image.base64_data),
                stored_at,
            ),
        )
        conn.execute(
            """
            update image_sources set
                final_url = ?, content_sha256 = ?, http_status = ?,
                content_type = ?, etag = ?, last_modified = ?,
                status = 'downloaded', downloaded_at = ?
            where source_url = ?
            """,
            (
                image.final_url,
                image.content_sha256,
                image.http_status,
                image.mime_type,
                image.etag,
                image.last_modified,
                stored_at,
                image.source_url,
            ),
        )
        conn.execute(
            """
            update content_image_links set content_sha256 = ?
            where source_url = ?
            """,
            (image.content_sha256, image.source_url),
        )
        conn.execute(
            """
            update image_download_failures set resolved_at = ?
            where source_url = ? and resolved_at = ''
            """,
            (stored_at, image.source_url),
        )


def _store_failure(
    conn: sqlite3.Connection,
    *,
    source_url: str,
    error: Exception,
) -> None:
    failed_at = utc_now()
    with conn:
        conn.execute(
            "update image_sources set status='error' where source_url=?",
            (source_url,),
        )
        conn.execute(
            """
            update image_download_failures set resolved_at = ?
            where source_url = ? and resolved_at = ''
            """,
            (failed_at, source_url),
        )
        conn.execute(
            """
            insert into image_download_failures (
                source_url, error_type, error_message, failed_at
            ) values (?, ?, ?, ?)
            """,
            (source_url, type(error).__name__, str(error), failed_at),
        )


def download_pending_images(
    conn: sqlite3.Connection,
    *,
    session: requests.Session,
    timeout: float,
    max_bytes: int,
    interval: float,
    max_images: int = 0,
    force_refresh: bool = False,
    retry_failures: bool = True,
    downloader=download_image,
) -> dict[str, int]:
    if force_refresh:
        condition = "1 = 1"
    elif retry_failures:
        condition = "status != 'downloaded'"
    else:
        condition = "status = 'pending'"
    rows = conn.execute(
        f"select source_url from image_sources where {condition} order by source_url"
    ).fetchall()
    if max_images > 0:
        rows = rows[:max_images]
    downloaded = failed = source_urls_attempted = 0
    for index, row in enumerate(rows, start=1):
        source_url = row["source_url"]
        try:
            source_urls_attempted += 1
            image = downloader(
                session,
                source_url,
                timeout=timeout,
                max_bytes=max_bytes,
            )
            _store_download(conn, image)
            downloaded += 1
        except Exception as error:
            _store_failure(conn, source_url=source_url, error=error)
            failed += 1
        if interval > 0 and index < len(rows):
            time.sleep(interval)
        if index == 1 or index % 25 == 0 or index == len(rows):
            print(
                json.dumps(
                    {
                        "stage": "tgb_author_images",
                        "attempted": index,
                        "planned": len(rows),
                        "downloaded": downloaded,
                        "failed": failed,
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
    return {
        "planned_this_run": len(rows),
        "source_urls_attempted_this_run": source_urls_attempted,
        "downloaded_this_run": downloaded,
        "failed_this_run": failed,
    }


def audit_base64_assets(conn: sqlite3.Connection) -> dict[str, object]:
    verified = 0
    failures: list[dict[str, str]] = []
    for row in conn.execute(
        """
        select content_sha256, byte_size, base64_data, base64_char_count
        from image_assets order by content_sha256
        """
    ).fetchall():
        try:
            decoded = base64.b64decode(row["base64_data"], validate=True)
            if len(decoded) != int(row["byte_size"]):
                raise ImageDownloadError("decoded_byte_size_mismatch")
            if len(row["base64_data"]) != int(row["base64_char_count"]):
                raise ImageDownloadError("base64_char_count_mismatch")
            if hashlib.sha256(decoded).hexdigest() != row["content_sha256"]:
                raise ImageDownloadError("decoded_sha256_mismatch")
            verified += 1
        except Exception as error:
            failures.append(
                {
                    "content_sha256": row["content_sha256"],
                    "reason": str(error),
                }
            )
    return {
        "assets": verified + len(failures),
        "verified": verified,
        "failed": len(failures),
        "failure_sample": failures[:20],
    }


def build_summary(
    conn: sqlite3.Connection,
    *,
    author_id: str,
    inventory: dict[str, int],
    run_stats: dict[str, int],
    canonical_db: Path,
    canonical_sha256: str,
    reply_feed_db: Path | None,
    reply_feed_sha256: str,
    media_db: Path,
) -> dict[str, object]:
    source_status = {
        row["status"]: int(row["row_count"])
        for row in conn.execute(
            "select status, count(*) as row_count from image_sources group by status"
        ).fetchall()
    }
    link_status = conn.execute(
        """
        select count(*) as total,
               sum(case when content_sha256 is not null then 1 else 0 end) as resolved
        from content_image_links where author_id = ?
        """,
        (author_id,),
    ).fetchone()
    unresolved_failures = int(
        conn.execute(
            "select count(*) from image_download_failures where resolved_at = ''"
        ).fetchone()[0]
    )
    asset_audit = audit_base64_assets(conn)
    unique_asset_bytes = int(
        conn.execute("select coalesce(sum(byte_size), 0) from image_assets").fetchone()[0]
    )
    total_links = int(link_status["total"] or 0)
    resolved_links = int(link_status["resolved"] or 0)
    complete = bool(
        source_status.get("downloaded", 0) == inventory["unique_source_urls"]
        and total_links == inventory["main_post_links"] + inventory["author_reply_links"]
        and resolved_links == total_links
        and unresolved_failures == 0
        and asset_audit["failed"] == 0
    )
    return {
        "schema_version": "1.1.0-tgb-author-image-base64-archive",
        "scope": {
            "author_id": author_id,
            "included": ["main_post", "author_reply"],
            "excluded": ["third_party_comment"],
        },
        "storage": {
            "database": display_path(media_db),
            "mode": "content-addressed-base64-text",
            "canonical_database": display_path(canonical_db),
            "canonical_database_sha256": canonical_sha256,
            "canonical_database_mutated": False,
            "reply_feed_database": (
                display_path(reply_feed_db) if reply_feed_db is not None else ""
            ),
            "reply_feed_database_sha256": reply_feed_sha256,
            "reply_feed_database_mutated": False,
        },
        "inventory": inventory,
        "run": run_stats,
        "coverage": {
            "source_status": source_status,
            "content_links": total_links,
            "resolved_content_links": resolved_links,
            "unique_assets": asset_audit["assets"],
            "unique_asset_bytes": unique_asset_bytes,
            "base64_audit": asset_audit,
            "unresolved_failures": unresolved_failures,
            "complete": complete,
        },
        "retrieved_at": utc_now(),
        "green": complete,
    }


def run(args: argparse.Namespace) -> dict[str, object]:
    canonical_db = Path(args.canonical_db).expanduser().resolve()
    reply_feed_db = (
        Path(args.reply_feed_db).expanduser().resolve()
        if args.reply_feed_db
        else None
    )
    media_db = Path(args.media_db).expanduser().resolve()
    summary_path = Path(args.summary).expanduser().resolve()
    canonical_sha256 = sha256_file(canonical_db)
    reply_feed_sha256 = sha256_file(reply_feed_db) if reply_feed_db else ""
    links = load_content_image_links(
        canonical_db,
        author_id=args.author_id,
        reply_feed_db=reply_feed_db,
    )
    conn = connect_media_db(media_db)
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": args.user_agent,
            "Referer": "https://www.tgb.cn/",
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        }
    )
    try:
        inventory = sync_inventory(
            conn,
            links=links,
            canonical_db=canonical_db,
            canonical_sha256=canonical_sha256,
            reply_feed_db=reply_feed_db,
            reply_feed_sha256=reply_feed_sha256,
            author_id=args.author_id,
        )
        run_stats = download_pending_images(
            conn,
            session=session,
            timeout=args.timeout,
            max_bytes=args.max_bytes,
            interval=args.interval,
            max_images=args.max_images,
            force_refresh=args.force_refresh,
            retry_failures=not args.pending_only,
        )
        summary = build_summary(
            conn,
            author_id=args.author_id,
            inventory=inventory,
            run_stats=run_stats,
            canonical_db=canonical_db,
            canonical_sha256=canonical_sha256,
            reply_feed_db=reply_feed_db,
            reply_feed_sha256=reply_feed_sha256,
            media_db=media_db,
        )
        conn.execute("pragma wal_checkpoint(truncate)")
    finally:
        conn.close()
        session.close()
    summary["storage"]["database_sha256"] = sha256_file(media_db)
    summary["storage"]["database_bytes"] = media_db.stat().st_size
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="将目标账号主贴和本人回复图片去重后以Base64存入独立SQLite"
    )
    parser.add_argument(
        "--user-id",
        "--author-id",
        dest="author_id",
        required=True,
        help="目标淘股吧账号的不可变user_id",
    )
    parser.add_argument("--canonical-db", default="")
    parser.add_argument(
        "--reply-feed-db",
        default="",
        help="可选：tgb_user_replies.py 产出的账号回贴全文SQLite",
    )
    parser.add_argument("--media-db", default="")
    parser.add_argument("--summary", default="")
    parser.add_argument("--max-images", type=int, default=0)
    parser.add_argument("--interval", type=float, default=0.35)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--max-bytes", type=int, default=25 * 1024 * 1024)
    parser.add_argument("--force-refresh", action="store_true")
    parser.add_argument(
        "--pending-only",
        action="store_true",
        help="只下载本轮新增pending URL，不重复请求既有失败URL",
    )
    parser.add_argument("--user-agent", default="Mozilla/5.0")
    args = parser.parse_args()
    if not args.author_id.isdigit():
        parser.error("--user-id must contain digits only")
    if (
        args.max_images < 0
        or args.interval < 0
        or args.timeout <= 0
        or args.max_bytes <= 0
    ):
        parser.error("--max-images/--interval/--timeout/--max-bytes out of range")
    args.canonical_db = args.canonical_db or str(
        PROJECT_ROOT / "data" / f"tgb-user-{args.author_id}.sqlite"
    )
    args.media_db = args.media_db or str(
        PROJECT_ROOT / "data" / f"tgb-user-{args.author_id}-media.sqlite"
    )
    args.summary = args.summary or str(
        PROJECT_ROOT / "data" / f"tgb-user-{args.author_id}-media-summary.json"
    )
    return args


def main() -> None:
    print(json.dumps(run(parse_args()), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
