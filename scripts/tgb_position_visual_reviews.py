#!/usr/bin/env python3
"""Track human visual review of deduplicated TGB position screenshots.

OCR is useful for discovery and prefill, but visual review is the evidence owner
for source masking, visible identities and zero-position disclosure. Reviews are
append-only and bind to the original image SHA-256.
"""

from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any


IMPORTER_VERSION = "1.0.0-tgb-position-visual-review"
LAYOUT_STATES = {
    "fully-visible",
    "masked-active",
    "masked-positions",
    "mixed",
    "unreadable",
    "no-position-rows",
}
IDENTITY_STATES = {"visible", "source-masked", "unreadable"}
POSITION_STATES = {"active", "closed", "unknown"}
STATEMENT_TIME_BASES = {"image-explicit", "unknown"}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def stable_visual_review_id(
    *, author_id: str, content_sha256: str, reviewed_by: str, reviewed_at: str, basis_sha256: str
) -> str:
    anchor = "|".join(
        (author_id, content_sha256, reviewed_by, reviewed_at, basis_sha256)
    )
    return "tgb-visual-review-" + sha256_text(anchor)[:24]


VISUAL_SCHEMA_SQL = """
        create table if not exists transaction_slip_visual_reviews (
          visual_review_id text primary key,
          author_id text not null,
          content_sha256_at_review text not null,
          representative_document_id text not null,
          statement_time text not null,
          account_key text not null,
          layout_state text not null check(
            layout_state in (
              'fully-visible','masked-active','masked-positions','mixed',
              'unreadable','no-position-rows'
            )
          ),
          visible_rows integer not null,
          masked_active_rows integer not null,
          visible_closed_rows integer not null,
          unreadable_rows integer not null,
          evidence_json text not null,
          evidence_sha256 text not null,
          reviewed_by text not null,
          reviewed_at text not null,
          review_note text not null,
          importer_version text not null,
          created_at text not null,
          foreign key(content_sha256_at_review) references image_assets(content_sha256)
        );

        create table if not exists transaction_slip_visual_position_rows (
          visual_review_id text not null,
          visual_row_no integer not null,
          identity_state text not null check(
            identity_state in ('visible','source-masked','unreadable')
          ),
          position_state text not null check(
            position_state in ('active','closed','unknown')
          ),
          stock_code text not null default '',
          stock_name text not null default '',
          holding_quantity real,
          available_quantity real,
          cumulative_profit_loss real,
          daily_profit_loss real,
          locator_json text not null,
          review_note text not null default '',
          primary key(visual_review_id,visual_row_no),
          foreign key(visual_review_id) references transaction_slip_visual_reviews(visual_review_id)
        );

        create index if not exists idx_tgb_visual_reviews_author_sha
          on transaction_slip_visual_reviews(author_id,content_sha256_at_review,reviewed_at);
        create index if not exists idx_tgb_visual_rows_identity_position
          on transaction_slip_visual_position_rows(identity_state,position_state,stock_name);
        """


def _migrate_layout_state_check(conn: sqlite3.Connection) -> None:
    table = conn.execute(
        "select sql from sqlite_master where type='table' "
        "and name='transaction_slip_visual_reviews'"
    ).fetchone()
    if table is None or "masked-positions" in str(table[0]):
        return
    rows_table = conn.execute(
        "select 1 from sqlite_master where type='table' "
        "and name='transaction_slip_visual_position_rows'"
    ).fetchone()
    if rows_table is None:
        raise RuntimeError("visual_review_rows_table_missing_during_migration")
    conn.commit()
    conn.execute("pragma foreign_keys=off")
    try:
        conn.executescript(
            """
            begin immediate;
            alter table transaction_slip_visual_position_rows
              rename to transaction_slip_visual_position_rows_legacy;
            alter table transaction_slip_visual_reviews
              rename to transaction_slip_visual_reviews_legacy;
            drop index if exists idx_tgb_visual_reviews_author_sha;
            drop index if exists idx_tgb_visual_rows_identity_position;
            """
            + VISUAL_SCHEMA_SQL
            + """
            insert into transaction_slip_visual_reviews
              select * from transaction_slip_visual_reviews_legacy;
            insert into transaction_slip_visual_position_rows
              select * from transaction_slip_visual_position_rows_legacy;
            drop table transaction_slip_visual_position_rows_legacy;
            drop table transaction_slip_visual_reviews_legacy;
            commit;
            """
        )
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise
    finally:
        conn.execute("pragma foreign_keys=on")


def init_schema(conn: sqlite3.Connection) -> None:
    _migrate_layout_state_check(conn)
    conn.execute("pragma foreign_keys=on")
    conn.executescript(VISUAL_SCHEMA_SQL)
    conn.commit()


def _iso_datetime(value: Any, field: str) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"missing_{field}")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"invalid_{field}:{text}") from error
    if parsed.tzinfo is None:
        raise ValueError(f"timezone_required_{field}")
    return parsed


def _zero(value: Any) -> bool:
    try:
        return abs(float(value)) < 1e-9
    except (TypeError, ValueError):
        return False


def validate_visual_review(review: dict[str, Any]) -> None:
    layout_state = str(review.get("layout_state") or "")
    if layout_state not in LAYOUT_STATES:
        raise ValueError(f"invalid_layout_state:{layout_state}")
    statement_time_basis = str(
        review.get("statement_time_basis") or "image-explicit"
    )
    if statement_time_basis not in STATEMENT_TIME_BASES:
        raise ValueError(f"invalid_statement_time_basis:{statement_time_basis}")
    statement_time = str(review.get("statement_time") or "").strip()
    if statement_time_basis == "image-explicit":
        _iso_datetime(statement_time, "statement_time")
    elif statement_time:
        raise ValueError("unknown_statement_time_must_be_empty")
    _iso_datetime(review.get("reviewed_at"), "reviewed_at")
    if not str(review.get("reviewed_by") or "").strip():
        raise ValueError("reviewed_by_required")
    if not str(review.get("review_note") or "").strip():
        raise ValueError("review_note_required")
    rows = review.get("rows")
    if not isinstance(rows, list):
        raise ValueError("rows_must_be_list")

    seen: set[int] = set()
    visible_rows = masked_rows = masked_active_rows = visible_closed_rows = unreadable_rows = 0
    for row in rows:
        row_no = int(row.get("visual_row_no") or 0)
        if row_no <= 0 or row_no in seen:
            raise ValueError(f"invalid_or_duplicate_visual_row_no:{row_no}")
        seen.add(row_no)
        identity_state = str(row.get("identity_state") or "")
        position_state = str(row.get("position_state") or "")
        if identity_state not in IDENTITY_STATES:
            raise ValueError(f"invalid_identity_state:{identity_state}")
        if position_state not in POSITION_STATES:
            raise ValueError(f"invalid_position_state:{position_state}")
        stock_code = str(row.get("stock_code") or "").strip()
        stock_name = str(row.get("stock_name") or "").strip()
        if identity_state == "source-masked" and (stock_code or stock_name):
            raise ValueError(f"masked_row_cannot_store_public_identity:{row_no}")
        if identity_state == "source-masked":
            masked_rows += 1
        if identity_state == "visible" and not stock_code and not stock_name:
            raise ValueError(f"visible_row_identity_required:{row_no}")
        if identity_state == "visible":
            visible_rows += 1
        if identity_state == "source-masked" and position_state == "active":
            masked_active_rows += 1
        if identity_state == "visible" and position_state == "closed":
            if not _zero(row.get("holding_quantity")) or not _zero(
                row.get("available_quantity")
            ):
                raise ValueError(f"visible_closed_row_requires_zero_position:{row_no}")
            visible_closed_rows += 1
        if identity_state == "unreadable":
            unreadable_rows += 1

    expected = {
        "visible_rows": visible_rows,
        "masked_active_rows": masked_active_rows,
        "visible_closed_rows": visible_closed_rows,
        "unreadable_rows": unreadable_rows,
    }
    for key, actual in expected.items():
        if int(review.get(key, -1)) != actual:
            raise ValueError(
                f"review_count_mismatch:{key}:expected={actual}:actual={review.get(key)}"
            )
    if layout_state == "no-position-rows" and rows:
        raise ValueError("no_position_rows_layout_must_have_empty_rows")
    if layout_state == "masked-active" and masked_active_rows == 0:
        raise ValueError("masked_active_layout_requires_masked_active_row")
    if layout_state == "masked-positions" and (masked_rows == 0 or visible_rows > 0):
        raise ValueError("masked_positions_layout_requires_only_masked_rows")
    if layout_state == "fully-visible" and (masked_active_rows or unreadable_rows):
        raise ValueError("fully_visible_layout_has_hidden_or_unreadable_rows")


def _verify_anchor(
    conn: sqlite3.Connection, *, author_id: str, review: dict[str, Any]
) -> sqlite3.Row:
    document_id = str(review.get("representative_document_id") or "").strip()
    content_sha256 = str(review.get("content_sha256") or "").strip()
    row = conn.execute(
        """
        select document_id,author_id,content_sha256,broker_name_ocr,
               account_label_masked,document_type
        from transaction_slip_documents where document_id=?
        """,
        (document_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"representative_document_missing:{document_id}")
    if str(row["author_id"]) != author_id:
        raise ValueError(f"representative_document_author_mismatch:{document_id}")
    if str(row["document_type"]) != "position_snapshot":
        raise ValueError(f"representative_document_not_position_snapshot:{document_id}")
    if str(row["content_sha256"]) != content_sha256:
        raise ValueError(f"representative_document_sha_mismatch:{document_id}")
    account_key = "|".join(
        (str(row["broker_name_ocr"]), str(row["account_label_masked"]))
    )
    if account_key != str(review.get("account_key") or ""):
        raise ValueError(f"review_account_key_mismatch:{document_id}")
    asset = conn.execute(
        "select base64_data from image_assets where content_sha256=?", (content_sha256,)
    ).fetchone()
    if asset is None:
        raise ValueError(f"review_image_asset_missing:{content_sha256}")
    try:
        raw = base64.b64decode(asset[0], validate=True)
    except Exception as error:
        raise ValueError(f"review_image_base64_invalid:{content_sha256}") from error
    if hashlib.sha256(raw).hexdigest() != content_sha256:
        raise ValueError(f"review_image_sha256_invalid:{content_sha256}")
    return row


def import_visual_reviews(
    conn: sqlite3.Connection,
    *,
    author_id: str,
    reviews: list[dict[str, Any]],
    dry_run: bool = False,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "planned": len(reviews),
        "imported": 0,
        "duplicates": 0,
        "rejected": 0,
        "items": [],
        "errors": [],
    }
    tables_exist = bool(
        conn.execute(
            "select 1 from sqlite_master where type='table' "
            "and name='transaction_slip_visual_reviews'"
        ).fetchone()
    )
    created_at = utc_now()
    for review in reviews:
        try:
            validate_visual_review(review)
            _verify_anchor(conn, author_id=author_id, review=review)
            basis_json = canonical_json(review)
            basis_sha256 = sha256_text(basis_json)
            review_id = stable_visual_review_id(
                author_id=author_id,
                content_sha256=str(review["content_sha256"]),
                reviewed_by=str(review["reviewed_by"]),
                reviewed_at=str(review["reviewed_at"]),
                basis_sha256=basis_sha256,
            )
            existing = (
                conn.execute(
                    "select evidence_sha256 from transaction_slip_visual_reviews "
                    "where visual_review_id=?",
                    (review_id,),
                ).fetchone()
                if tables_exist
                else None
            )
            if existing is not None:
                if str(existing[0]) != basis_sha256:
                    raise ValueError(f"existing_visual_review_conflict:{review_id}")
                result["duplicates"] += 1
                result["items"].append(
                    {"visual_review_id": review_id, "status": "duplicate"}
                )
                continue
            if not dry_run:
                with conn:
                    conn.execute(
                        """
                        insert into transaction_slip_visual_reviews (
                          visual_review_id,author_id,content_sha256_at_review,
                          representative_document_id,statement_time,account_key,
                          layout_state,visible_rows,masked_active_rows,
                          visible_closed_rows,unreadable_rows,evidence_json,
                          evidence_sha256,reviewed_by,reviewed_at,review_note,
                          importer_version,created_at
                        ) values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            review_id,
                            author_id,
                            review["content_sha256"],
                            review["representative_document_id"],
                            review["statement_time"],
                            review["account_key"],
                            review["layout_state"],
                            int(review["visible_rows"]),
                            int(review["masked_active_rows"]),
                            int(review["visible_closed_rows"]),
                            int(review["unreadable_rows"]),
                            basis_json,
                            basis_sha256,
                            review["reviewed_by"],
                            review["reviewed_at"],
                            review["review_note"],
                            IMPORTER_VERSION,
                            created_at,
                        ),
                    )
                    for row in review["rows"]:
                        conn.execute(
                            """
                            insert into transaction_slip_visual_position_rows (
                              visual_review_id,visual_row_no,identity_state,
                              position_state,stock_code,stock_name,holding_quantity,
                              available_quantity,cumulative_profit_loss,
                              daily_profit_loss,locator_json,review_note
                            ) values (?,?,?,?,?,?,?,?,?,?,?,?)
                            """,
                            (
                                review_id,
                                int(row["visual_row_no"]),
                                row["identity_state"],
                                row["position_state"],
                                str(row.get("stock_code") or ""),
                                str(row.get("stock_name") or ""),
                                row.get("holding_quantity"),
                                row.get("available_quantity"),
                                row.get("cumulative_profit_loss"),
                                row.get("daily_profit_loss"),
                                canonical_json(row.get("locator") or {}),
                                str(row.get("review_note") or ""),
                            ),
                        )
            result["imported"] += 1
            result["items"].append(
                {
                    "visual_review_id": review_id,
                    "content_sha256": review["content_sha256"],
                    "status": "dry-run" if dry_run else "imported",
                }
            )
        except Exception as error:
            result["rejected"] += 1
            result["errors"].append(f"{type(error).__name__}:{error}")
    return result


def review_coverage(conn: sqlite3.Connection, author_id: str) -> dict[str, Any]:
    total = int(
        conn.execute(
            """
            select count(distinct content_sha256) from transaction_slip_documents
            where author_id=? and document_type='position_snapshot'
            """,
            (author_id,),
        ).fetchone()[0]
        or 0
    )
    reviewed = int(
        conn.execute(
            """
            select count(distinct content_sha256_at_review)
            from transaction_slip_visual_reviews where author_id=?
            """,
            (author_id,),
        ).fetchone()[0]
        or 0
    )
    layout_counts = {
        str(row[0]): int(row[1])
        for row in conn.execute(
            """
            select v.layout_state,count(*) from transaction_slip_visual_reviews v
            where v.author_id=? and v.rowid=(
              select vv.rowid from transaction_slip_visual_reviews vv
              where vv.author_id=v.author_id
                and vv.content_sha256_at_review=v.content_sha256_at_review
              order by julianday(vv.reviewed_at) desc,vv.rowid desc limit 1
            ) group by v.layout_state
            """,
            (author_id,),
        )
    }
    return {
        "unique_position_images": total,
        "human_reviewed_unique_images": reviewed,
        "remaining_unique_images": total - reviewed,
        "layout_state_counts": layout_counts,
        "complete": bool(total > 0 and reviewed == total),
    }


def export_review_queue(
    conn: sqlite3.Connection, *, author_id: str
) -> dict[str, Any]:
    rows = conn.execute(
        """
        with representatives as (
          select d.*,
                 row_number() over (
                   partition by d.content_sha256
                   order by case when d.statement_date>='2018-11-01' then 0 else 1 end,
                            d.statement_date desc,d.source_created_at desc,d.document_id
                 ) as rn
          from transaction_slip_documents d
          where d.author_id=? and d.document_type='position_snapshot'
        )
        select r.content_sha256,r.document_id,r.statement_date,r.source_created_at,
               r.source_url,r.broker_name_ocr,r.account_label_masked,
               case when r.statement_date>='2018-11-01' then 'late-priority' else 'earlier' end as priority,
               exists(
                 select 1 from transaction_slip_visual_reviews v
                 where v.author_id=r.author_id
                   and v.content_sha256_at_review=r.content_sha256
               ) as already_reviewed
        from representatives r where r.rn=1
        order by case when priority='late-priority' then 0 else 1 end,
                 r.statement_date desc,r.source_created_at desc,r.content_sha256
        """,
        (author_id,),
    ).fetchall()
    items = [
        {
            "content_sha256": row["content_sha256"],
            "representative_document_id": row["document_id"],
            "statement_date": row["statement_date"],
            "source_created_at": row["source_created_at"],
            "source_url": row["source_url"],
            "account_key": "|".join(
                (str(row["broker_name_ocr"]), str(row["account_label_masked"]))
            ),
            "priority": row["priority"],
            "already_reviewed": bool(row["already_reviewed"]),
        }
        for row in rows
    ]
    return {
        "schema_version": "1.0.0-tgb-position-visual-review-queue",
        "author_id": author_id,
        "items": items,
        "counts": {
            "all": len(items),
            "late_priority": sum(item["priority"] == "late-priority" for item in items),
            "earlier": sum(item["priority"] == "earlier" for item in items),
            "already_reviewed": sum(item["already_reviewed"] for item in items),
        },
        "generated_at": utc_now(),
    }


def load_reviews(path: str) -> list[dict[str, Any]]:
    if not path:
        return []
    payload = json.loads(Path(path).expanduser().resolve().read_text(encoding="utf-8"))
    reviews = payload.get("reviews")
    if not isinstance(reviews, list):
        raise ValueError("manifest_reviews_must_be_list")
    return [dict(review) for review in reviews]


def run(args: argparse.Namespace) -> dict[str, Any]:
    media_path = Path(args.media_db).expanduser().resolve()
    if not media_path.exists():
        raise FileNotFoundError(f"media_database_missing:{media_path}")
    reviews = load_reviews(args.reviews_manifest)
    if not reviews and not args.export_queue:
        raise ValueError("reviews_manifest_or_export_queue_required")
    conn = sqlite3.connect(media_path)
    conn.row_factory = sqlite3.Row
    try:
        if not args.dry_run:
            init_schema(conn)
        import_result = import_visual_reviews(
            conn,
            author_id=args.user_id,
            reviews=reviews,
            dry_run=args.dry_run,
        )
        if args.export_queue:
            queue = export_review_queue(conn, author_id=args.user_id)
            queue_path = Path(args.export_queue).expanduser().resolve()
            queue_path.parent.mkdir(parents=True, exist_ok=True)
            queue_path.write_text(
                json.dumps(queue, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        coverage = (
            review_coverage(conn, args.user_id)
            if not args.dry_run
            else {"dry_run": True}
        )
        check = str(conn.execute("pragma integrity_check").fetchone()[0])
        summary = {
            "schema_version": "1.0.0-tgb-position-visual-review-summary",
            "user_id": args.user_id,
            "media_database": str(media_path),
            "source_contract": {
                "review_unit_is_unique_image_sha256": True,
                "ocr_is_assistive_not_authoritative": True,
                "missing_ocr_is_not_source_masking": True,
                "reviews_are_append_only": True,
            },
            "review_import": import_result,
            "coverage": coverage,
            "queue_output": str(Path(args.export_queue).expanduser().resolve())
            if args.export_queue
            else "",
            "sqlite_integrity": check,
            "green": bool(check == "ok" and import_result["rejected"] == 0),
            "evaluated_at": utc_now(),
        }
    finally:
        conn.close()
    if args.summary:
        output = Path(args.summary).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="维护淘股吧去重持仓截图的追加式人工视觉审核"
    )
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--media-db", required=True)
    parser.add_argument("--reviews-manifest", default="")
    parser.add_argument("--export-queue", default="")
    parser.add_argument("--summary", default="")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
