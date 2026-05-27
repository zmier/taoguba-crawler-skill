from __future__ import annotations

from datetime import datetime, timedelta, timezone
import sqlite3


def enqueue(
    conn: sqlite3.Connection,
    url: str,
    kind: str,
    priority: int = 0,
    now: str | None = None,
) -> bool:
    timestamp = now or _now()
    cursor = conn.execute(
        """
        insert or ignore into crawl_queue (
            url, kind, status, priority, attempts, last_error,
            next_run_at, created_at, updated_at
        )
        values (?, ?, 'pending', ?, 0, '', null, ?, ?)
        """,
        (url, kind, priority, timestamp, timestamp),
    )
    conn.commit()
    return cursor.rowcount > 0


def claim_next(
    conn: sqlite3.Connection,
    kind: str | None = None,
    now: str | None = None,
) -> sqlite3.Row | None:
    timestamp = now or _now()
    params: list[str] = [timestamp]
    kind_clause = ""
    if kind is not None:
        kind_clause = "and kind = ?"
        params.append(kind)

    row = conn.execute(
        f"""
        select *
        from crawl_queue
        where status = 'pending'
          and (next_run_at is null or next_run_at <= ?)
          {kind_clause}
        order by priority desc, created_at asc, url asc
        limit 1
        """,
        params,
    ).fetchone()
    if row is None:
        return None

    conn.execute(
        """
        update crawl_queue
        set status = 'running', updated_at = ?
        where url = ? and status = 'pending'
        """,
        (timestamp, row["url"]),
    )
    conn.commit()
    return get_queue_item(conn, row["url"])


def mark_done(conn: sqlite3.Connection, url: str, now: str | None = None) -> None:
    timestamp = now or _now()
    conn.execute(
        """
        update crawl_queue
        set status = 'done',
            last_error = '',
            next_run_at = null,
            updated_at = ?
        where url = ?
        """,
        (timestamp, url),
    )
    conn.commit()


def mark_failed(
    conn: sqlite3.Connection,
    url: str,
    error: str,
    max_attempts: int = 3,
    backoff_seconds: int = 60,
    now: str | None = None,
) -> None:
    timestamp = now or _now()
    row = get_queue_item(conn, url)
    if row is None:
        raise ValueError(f"unknown queue url: {url}")

    attempts = int(row["attempts"]) + 1
    status = "failed" if attempts >= max_attempts else "pending"
    next_run_at = None
    if status == "pending":
        next_run_at = _add_seconds(timestamp, backoff_seconds * attempts)

    conn.execute(
        """
        update crawl_queue
        set status = ?,
            attempts = ?,
            last_error = ?,
            next_run_at = ?,
            updated_at = ?
        where url = ?
        """,
        (status, attempts, error, next_run_at, timestamp, url),
    )
    conn.execute(
        """
        insert into failures (url, kind, error, attempts, created_at)
        values (?, ?, ?, ?, ?)
        """,
        (url, row["kind"], error, attempts, timestamp),
    )
    conn.commit()


def reset_stale_running(
    conn: sqlite3.Connection,
    older_than_seconds: int = 3600,
    now: str | None = None,
) -> int:
    timestamp = now or _now()
    cutoff = _add_seconds(timestamp, -older_than_seconds)
    cursor = conn.execute(
        """
        update crawl_queue
        set status = 'pending',
            updated_at = ?
        where status = 'running'
          and updated_at <= ?
        """,
        (timestamp, cutoff),
    )
    conn.commit()
    return cursor.rowcount


def get_queue_item(conn: sqlite3.Connection, url: str) -> sqlite3.Row | None:
    return conn.execute("select * from crawl_queue where url = ?", (url,)).fetchone()


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _add_seconds(timestamp: str, seconds: int) -> str:
    return (datetime.fromisoformat(timestamp) + timedelta(seconds=seconds)).isoformat()
