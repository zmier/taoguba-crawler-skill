#!/usr/bin/env python3
"""Record auditable links from source-masked positions to later disclosures.

The source image remains canonical.  This adapter never treats missing OCR text
as proof of masking and never promotes a machine match to a confirmed fact.
Visual annotations enter as immutable claims; human decisions are append-only
review events.
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


IMPORTER_VERSION = "1.0.0-tgb-delayed-disclosure"
RELATION_KIND = "masked_position_later_public_sale_disclosure"
REVIEW_STATES = {
    "candidate",
    "human-confirmed",
    "rejected",
    "withdrawn",
    "source-changed",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def stable_claim_id(
    *,
    author_id: str,
    source_document_id: str,
    source_content_sha256: str,
    disclosure_document_id: str,
    disclosure_content_sha256: str,
    disclosed_stock_code: str,
    disclosed_stock_name: str,
) -> str:
    anchor = "|".join(
        (
            author_id,
            RELATION_KIND,
            source_document_id,
            source_content_sha256,
            disclosure_document_id,
            disclosure_content_sha256,
            disclosed_stock_code,
            disclosed_stock_name,
        )
    )
    return "tgb-identity-" + sha256_text(anchor)[:24]


def stable_review_event_id(
    *,
    claim_id: str,
    state: str,
    reviewed_by: str,
    reviewed_at: str,
    basis_sha256: str,
    review_note: str,
) -> str:
    anchor = "|".join(
        (claim_id, state, reviewed_by, reviewed_at, basis_sha256, review_note)
    )
    return "tgb-identity-review-" + sha256_text(anchor)[:24]


def init_schema(conn: sqlite3.Connection) -> None:
    conn.execute("pragma foreign_keys=on")
    conn.executescript(
        """
        create table if not exists transaction_slip_identity_claims (
          claim_id text primary key,
          author_id text not null,
          relation_kind text not null,
          source_document_id text not null,
          source_record_id_at_assertion text not null,
          source_url_at_assertion text not null,
          source_content_sha256_at_assertion text not null,
          source_statement_time text not null,
          source_account_key text not null,
          source_locator_json text not null,
          disclosure_document_id text not null,
          disclosure_source_record_id_at_assertion text not null,
          disclosure_url_at_assertion text not null,
          disclosure_content_sha256_at_assertion text not null,
          disclosure_statement_time text not null,
          disclosure_account_key text not null,
          disclosure_locator_json text not null,
          publicly_disclosed_stock_code text not null default '',
          publicly_disclosed_stock_name text not null default '',
          confidence_score integer not null,
          machine_state text not null,
          evidence_basis_json text not null,
          basis_sha256 text not null,
          importer_version text not null,
          created_at text not null,
          unique(
            author_id,relation_kind,
            source_document_id,source_content_sha256_at_assertion,
            disclosure_document_id,disclosure_content_sha256_at_assertion,
            publicly_disclosed_stock_code,publicly_disclosed_stock_name
          )
        );

        create table if not exists transaction_slip_identity_claim_reviews (
          review_event_id text primary key,
          claim_id text not null,
          state text not null check(
            state in ('candidate','human-confirmed','rejected','withdrawn','source-changed')
          ),
          reviewed_by text not null,
          review_note text not null,
          reviewed_at text not null,
          basis_sha256 text not null,
          created_at text not null,
          foreign key(claim_id) references transaction_slip_identity_claims(claim_id)
        );

        create index if not exists idx_tgb_identity_claims_author_state
          on transaction_slip_identity_claims(author_id,machine_state);
        create index if not exists idx_tgb_identity_claims_documents
          on transaction_slip_identity_claims(source_document_id,disclosure_document_id);
        create index if not exists idx_tgb_identity_reviews_claim_time
          on transaction_slip_identity_claim_reviews(claim_id,reviewed_at);
        """
    )
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


def evaluate_claim(claim: dict[str, Any]) -> dict[str, Any]:
    """Evaluate one visually annotated delayed-disclosure candidate.

    Scores rank candidates.  Hard rejections always win, and the highest
    machine state remains ``machine-strong-candidate``.
    """

    source = dict(claim.get("source") or {})
    disclosure = dict(claim.get("disclosure") or {})
    hard_rejections: list[str] = []

    source_time = _iso_datetime(source.get("statement_time"), "source_statement_time")
    disclosure_time = _iso_datetime(
        disclosure.get("statement_time"), "disclosure_statement_time"
    )
    if disclosure_time <= source_time:
        hard_rejections.append("disclosure_not_after_source")

    source_account = str(source.get("account_key") or "").strip()
    disclosure_account = str(disclosure.get("account_key") or "").strip()
    if not source_account or source_account != disclosure_account:
        hard_rejections.append("account_mismatch_or_missing")

    if source.get("source_mask_visually_confirmed") is not True:
        hard_rejections.append("source_mask_not_visually_confirmed")
    if int(source.get("anonymous_active_rows") or 0) != 1:
        hard_rejections.append("ambiguous_or_missing_anonymous_active_row")

    stock_code = str(disclosure.get("stock_code") or "").strip()
    stock_name = str(disclosure.get("stock_name") or "").strip()
    if not stock_code and not stock_name:
        hard_rejections.append("public_identity_missing")
    if disclosure.get("public_name_visually_confirmed") is not True:
        hard_rejections.append("public_identity_not_visually_confirmed")
    if disclosure.get("zero_position_visually_confirmed") is not True:
        hard_rejections.append("zero_position_not_visually_confirmed")
    if not _zero(disclosure.get("holding_quantity")) or not _zero(
        disclosure.get("available_quantity")
    ):
        hard_rejections.append("disclosed_position_not_zero")
    if int(disclosure.get("revealed_closed_rows") or 0) != 1:
        hard_rejections.append("ambiguous_or_missing_revealed_closed_row")

    trading_day_gap = int(claim.get("trading_day_gap", -1))
    if trading_day_gap < 0 or trading_day_gap > 3:
        hard_rejections.append("trading_day_gap_out_of_range")
    if claim.get("source_is_account_summary_only") is True or claim.get(
        "disclosure_is_account_summary_only"
    ) is True:
        hard_rejections.append("account_summary_only")

    candidate_set_size = int(claim.get("candidate_set_size") or 1)
    runner_up_gap = claim.get("runner_up_score_gap")
    if candidate_set_size > 1 and (
        runner_up_gap is None or float(runner_up_gap) < 15.0
    ):
        hard_rejections.append("candidate_margin_below_15")

    before_pnl = source.get("cumulative_profit_loss")
    after_pnl = disclosure.get("cumulative_profit_loss")
    daily_pnl = disclosure.get("daily_profit_loss")
    residual = residual_ratio = None
    pnl_points = 0
    if before_pnl is not None and after_pnl is not None and daily_pnl is not None:
        before_value = float(before_pnl)
        after_value = float(after_pnl)
        daily_value = float(daily_pnl)
        residual = abs((after_value - before_value) - daily_value)
        residual_ratio = residual / max(100.0, abs(daily_value))
        if residual_ratio <= 0.01:
            pnl_points = 20
        elif residual_ratio <= 0.03:
            pnl_points = 16
        elif residual_ratio <= 0.10:
            pnl_points = 8

    time_points = 15 if trading_day_gap == 0 else 13 if trading_day_gap == 1 else 8
    source_quality = bool(
        source.get("original_image_sha_verified") is True
        and disclosure.get("original_image_sha_verified") is True
        and source.get("source_mask_visually_confirmed") is True
        and disclosure.get("public_name_visually_confirmed") is True
        and disclosure.get("zero_position_visually_confirmed") is True
    )
    breakdown = {
        "same_account": 20 if source_account and source_account == disclosure_account else 0,
        "time_proximity": time_points if 0 <= trading_day_gap <= 3 else 0,
        "unique_assignment": (
            20
            if int(source.get("anonymous_active_rows") or 0) == 1
            and int(disclosure.get("revealed_closed_rows") or 0) == 1
            else 0
        ),
        "zero_position_disclosure": (
            15
            if disclosure.get("zero_position_visually_confirmed") is True
            and _zero(disclosure.get("holding_quantity"))
            and _zero(disclosure.get("available_quantity"))
            else 0
        ),
        "profit_loss_continuity": pnl_points,
        "portfolio_continuity": (
            5 if claim.get("portfolio_continuity_visually_confirmed") is True else 0
        ),
        "source_quality": 5 if source_quality else 0,
    }
    score = sum(breakdown.values())
    if hard_rejections:
        machine_state = "unresolved"
    elif score >= 90:
        machine_state = "machine-strong-candidate"
    elif score >= 70:
        machine_state = "human-review-candidate"
    else:
        machine_state = "unresolved"

    return {
        "score": score,
        "machine_state": machine_state,
        "hard_rejections": sorted(set(hard_rejections)),
        "score_breakdown": breakdown,
        "profit_loss_residual": residual,
        "profit_loss_residual_ratio": residual_ratio,
        "auto_confirmed": False,
        "human_review_required": machine_state != "unresolved",
    }


def _document(conn: sqlite3.Connection, document_id: str) -> sqlite3.Row:
    row = conn.execute(
        """
        select document_id,author_id,source_record_id,source_url,content_sha256,
               broker_name_ocr,account_label_masked,document_type
        from transaction_slip_documents where document_id=?
        """,
        (document_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"document_missing:{document_id}")
    return row


def _verify_document_anchor(
    conn: sqlite3.Connection,
    *,
    author_id: str,
    side: dict[str, Any],
    side_name: str,
) -> sqlite3.Row:
    document_id = str(side.get("document_id") or "").strip()
    expected_sha = str(side.get("content_sha256") or "").strip()
    row = _document(conn, document_id)
    if str(row["author_id"]) != author_id:
        raise ValueError(f"{side_name}_author_mismatch:{document_id}")
    if str(row["document_type"]) != "position_snapshot":
        raise ValueError(f"{side_name}_not_position_snapshot:{document_id}")
    if str(row["content_sha256"]) != expected_sha:
        raise ValueError(f"{side_name}_content_sha256_mismatch:{document_id}")
    database_account_key = "|".join(
        (str(row["broker_name_ocr"]), str(row["account_label_masked"]))
    )
    if database_account_key != str(side.get("account_key") or ""):
        raise ValueError(f"{side_name}_account_key_mismatch:{document_id}")
    asset = conn.execute(
        "select base64_data from image_assets where content_sha256=?", (expected_sha,)
    ).fetchone()
    if asset is None:
        raise ValueError(f"{side_name}_image_asset_missing:{expected_sha}")
    try:
        raw = base64.b64decode(asset[0], validate=True)
    except Exception as error:
        raise ValueError(f"{side_name}_image_base64_invalid:{expected_sha}") from error
    if hashlib.sha256(raw).hexdigest() != expected_sha:
        raise ValueError(f"{side_name}_image_sha256_invalid:{expected_sha}")
    return row


def _claim_basis(
    claim: dict[str, Any],
    evaluation: dict[str, Any],
    source_row: sqlite3.Row,
    disclosure_row: sqlite3.Row,
) -> dict[str, Any]:
    return {
        "relation_kind": RELATION_KIND,
        "claim_annotation": claim,
        "evaluation": evaluation,
        "source_database_anchor": {
            "document_id": source_row["document_id"],
            "source_record_id": source_row["source_record_id"],
            "source_url": source_row["source_url"],
            "content_sha256": source_row["content_sha256"],
        },
        "disclosure_database_anchor": {
            "document_id": disclosure_row["document_id"],
            "source_record_id": disclosure_row["source_record_id"],
            "source_url": disclosure_row["source_url"],
            "content_sha256": disclosure_row["content_sha256"],
        },
    }


def import_claims(
    conn: sqlite3.Connection,
    *,
    author_id: str,
    claims: list[dict[str, Any]],
    dry_run: bool = False,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "planned": len(claims),
        "imported": 0,
        "duplicates": 0,
        "rejected": 0,
        "items": [],
        "errors": [],
    }
    now = utc_now()
    claims_table_exists = bool(
        conn.execute(
            "select 1 from sqlite_master where type='table' "
            "and name='transaction_slip_identity_claims'"
        ).fetchone()
    )
    for claim in claims:
        try:
            source = dict(claim.get("source") or {})
            disclosure = dict(claim.get("disclosure") or {})
            evaluation = evaluate_claim(claim)
            if evaluation["hard_rejections"]:
                raise ValueError(
                    "hard_rejection:" + ",".join(evaluation["hard_rejections"])
                )
            source_row = _verify_document_anchor(
                conn, author_id=author_id, side=source, side_name="source"
            )
            disclosure_row = _verify_document_anchor(
                conn,
                author_id=author_id,
                side=disclosure,
                side_name="disclosure",
            )
            claim_id = stable_claim_id(
                author_id=author_id,
                source_document_id=source["document_id"],
                source_content_sha256=source["content_sha256"],
                disclosure_document_id=disclosure["document_id"],
                disclosure_content_sha256=disclosure["content_sha256"],
                disclosed_stock_code=str(disclosure.get("stock_code") or ""),
                disclosed_stock_name=str(disclosure.get("stock_name") or ""),
            )
            basis = _claim_basis(claim, evaluation, source_row, disclosure_row)
            basis_json = canonical_json(basis)
            basis_sha256 = sha256_text(basis_json)
            existing = (
                conn.execute(
                    "select basis_sha256 from transaction_slip_identity_claims where claim_id=?",
                    (claim_id,),
                ).fetchone()
                if claims_table_exists
                else None
            )
            if existing is not None:
                if str(existing[0]) != basis_sha256:
                    raise ValueError(f"existing_claim_basis_conflict:{claim_id}")
                result["duplicates"] += 1
                result["items"].append(
                    {
                        "claim_id": claim_id,
                        "basis_sha256": basis_sha256,
                        "machine_state": evaluation["machine_state"],
                        "status": "duplicate",
                    }
                )
                continue
            if not dry_run:
                with conn:
                    conn.execute(
                        """
                        insert into transaction_slip_identity_claims (
                          claim_id,author_id,relation_kind,
                          source_document_id,source_record_id_at_assertion,
                          source_url_at_assertion,source_content_sha256_at_assertion,
                          source_statement_time,source_account_key,source_locator_json,
                          disclosure_document_id,disclosure_source_record_id_at_assertion,
                          disclosure_url_at_assertion,
                          disclosure_content_sha256_at_assertion,
                          disclosure_statement_time,disclosure_account_key,
                          disclosure_locator_json,publicly_disclosed_stock_code,
                          publicly_disclosed_stock_name,confidence_score,machine_state,
                          evidence_basis_json,basis_sha256,importer_version,created_at
                        ) values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            claim_id,
                            author_id,
                            RELATION_KIND,
                            source["document_id"],
                            source_row["source_record_id"],
                            source_row["source_url"],
                            source["content_sha256"],
                            source["statement_time"],
                            source["account_key"],
                            canonical_json(source.get("locator") or {}),
                            disclosure["document_id"],
                            disclosure_row["source_record_id"],
                            disclosure_row["source_url"],
                            disclosure["content_sha256"],
                            disclosure["statement_time"],
                            disclosure["account_key"],
                            canonical_json(disclosure.get("locator") or {}),
                            str(disclosure.get("stock_code") or ""),
                            str(disclosure.get("stock_name") or ""),
                            evaluation["score"],
                            evaluation["machine_state"],
                            basis_json,
                            basis_sha256,
                            IMPORTER_VERSION,
                            now,
                        ),
                    )
                    review_event_id = stable_review_event_id(
                        claim_id=claim_id,
                        state="candidate",
                        reviewed_by=f"machine:{IMPORTER_VERSION}",
                        reviewed_at=now,
                        basis_sha256=basis_sha256,
                        review_note=evaluation["machine_state"],
                    )
                    conn.execute(
                        """
                        insert into transaction_slip_identity_claim_reviews (
                          review_event_id,claim_id,state,reviewed_by,review_note,
                          reviewed_at,basis_sha256,created_at
                        ) values (?,?,?,?,?,?,?,?)
                        """,
                        (
                            review_event_id,
                            claim_id,
                            "candidate",
                            f"machine:{IMPORTER_VERSION}",
                            evaluation["machine_state"],
                            now,
                            basis_sha256,
                            now,
                        ),
                    )
            result["imported"] += 1
            result["items"].append(
                {
                    "claim_id": claim_id,
                    "basis_sha256": basis_sha256,
                    "machine_state": evaluation["machine_state"],
                    "score": evaluation["score"],
                    "status": "dry-run" if dry_run else "imported",
                }
            )
        except Exception as error:
            result["rejected"] += 1
            result["errors"].append(f"{type(error).__name__}:{error}")
    return result


def append_reviews(
    conn: sqlite3.Connection,
    *,
    author_id: str,
    reviews: list[dict[str, Any]],
    dry_run: bool = False,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "planned": len(reviews),
        "appended": 0,
        "duplicates": 0,
        "rejected": 0,
        "errors": [],
    }
    created_at = utc_now()
    for review in reviews:
        try:
            claim_id = str(review.get("claim_id") or "").strip()
            state = str(review.get("state") or "").strip()
            reviewed_by = str(review.get("reviewed_by") or "").strip()
            reviewed_at = str(review.get("reviewed_at") or "").strip()
            review_note = str(review.get("review_note") or "").strip()
            expected_basis = str(review.get("expected_basis_sha256") or "").strip()
            if state not in REVIEW_STATES - {"candidate"}:
                raise ValueError(f"invalid_manual_review_state:{state}")
            if not reviewed_by or not review_note:
                raise ValueError("reviewer_and_note_required")
            _iso_datetime(reviewed_at, "reviewed_at")
            claim = conn.execute(
                """
                select * from transaction_slip_identity_claims
                where claim_id=? and author_id=?
                """,
                (claim_id, author_id),
            ).fetchone()
            if claim is None:
                raise ValueError(f"claim_missing_or_author_mismatch:{claim_id}")
            if expected_basis != str(claim["basis_sha256"]):
                raise ValueError(f"basis_sha256_mismatch:{claim_id}")
            stale = _claim_is_stale(conn, claim)
            if stale and state == "human-confirmed":
                raise ValueError(f"source_changed_cannot_confirm:{claim_id}")
            review_event_id = stable_review_event_id(
                claim_id=claim_id,
                state=state,
                reviewed_by=reviewed_by,
                reviewed_at=reviewed_at,
                basis_sha256=expected_basis,
                review_note=review_note,
            )
            existing = conn.execute(
                "select 1 from transaction_slip_identity_claim_reviews where review_event_id=?",
                (review_event_id,),
            ).fetchone()
            if existing is not None:
                result["duplicates"] += 1
                continue
            if not dry_run:
                with conn:
                    conn.execute(
                        """
                        insert into transaction_slip_identity_claim_reviews (
                          review_event_id,claim_id,state,reviewed_by,review_note,
                          reviewed_at,basis_sha256,created_at
                        ) values (?,?,?,?,?,?,?,?)
                        """,
                        (
                            review_event_id,
                            claim_id,
                            state,
                            reviewed_by,
                            review_note,
                            reviewed_at,
                            expected_basis,
                            created_at,
                        ),
                    )
            result["appended"] += 1
        except Exception as error:
            result["rejected"] += 1
            result["errors"].append(f"{type(error).__name__}:{error}")
    return result


def _claim_is_stale(conn: sqlite3.Connection, claim: sqlite3.Row) -> bool:
    current_source = conn.execute(
        "select content_sha256 from transaction_slip_documents where document_id=?",
        (claim["source_document_id"],),
    ).fetchone()
    current_disclosure = conn.execute(
        "select content_sha256 from transaction_slip_documents where document_id=?",
        (claim["disclosure_document_id"],),
    ).fetchone()
    return bool(
        current_source is None
        or current_disclosure is None
        or str(current_source[0]) != claim["source_content_sha256_at_assertion"]
        or str(current_disclosure[0])
        != claim["disclosure_content_sha256_at_assertion"]
    )


def claim_status_counts(conn: sqlite3.Connection, author_id: str) -> dict[str, Any]:
    claims = conn.execute(
        "select * from transaction_slip_identity_claims where author_id=?",
        (author_id,),
    ).fetchall()
    latest_states: dict[str, int] = {}
    stale = 0
    for claim in claims:
        if _claim_is_stale(conn, claim):
            stale += 1
        latest = conn.execute(
            """
            select state from transaction_slip_identity_claim_reviews
            where claim_id=? order by reviewed_at desc,rowid desc limit 1
            """,
            (claim["claim_id"],),
        ).fetchone()
        state = str(latest[0]) if latest else "unreviewed"
        latest_states[state] = latest_states.get(state, 0) + 1
    machine_states = {
        str(row[0]): int(row[1])
        for row in conn.execute(
            """
            select machine_state,count(*) from transaction_slip_identity_claims
            where author_id=? group by machine_state
            """,
            (author_id,),
        )
    }
    return {
        "claims": len(claims),
        "machine_state_counts": machine_states,
        "latest_review_state_counts": latest_states,
        "source_changed_claims": stale,
    }


def load_manifest(path: str, key: str) -> list[dict[str, Any]]:
    if not path:
        return []
    payload = json.loads(Path(path).expanduser().resolve().read_text(encoding="utf-8"))
    values = payload.get(key)
    if not isinstance(values, list):
        raise ValueError(f"manifest_{key}_must_be_list")
    return [dict(value) for value in values]


def run(args: argparse.Namespace) -> dict[str, Any]:
    media_path = Path(args.media_db).expanduser().resolve()
    if not media_path.exists():
        raise FileNotFoundError(f"media_database_missing:{media_path}")
    claims = load_manifest(args.claims_manifest, "claims")
    reviews = load_manifest(args.reviews_manifest, "reviews")
    if not claims and not reviews:
        raise ValueError("claims_or_reviews_manifest_required")

    conn = sqlite3.connect(media_path)
    conn.row_factory = sqlite3.Row
    try:
        if not args.dry_run:
            init_schema(conn)
        elif reviews:
            tables = {
                row[0]
                for row in conn.execute(
                    "select name from sqlite_master where type='table'"
                )
            }
            if "transaction_slip_identity_claims" not in tables:
                raise ValueError("identity_claim_tables_missing_for_review_dry_run")
        claim_result = import_claims(
            conn,
            author_id=args.user_id,
            claims=claims,
            dry_run=args.dry_run,
        )
        review_result = append_reviews(
            conn,
            author_id=args.user_id,
            reviews=reviews,
            dry_run=args.dry_run,
        )
        coverage = (
            claim_status_counts(conn, args.user_id)
            if not args.dry_run
            else {"claims": 0, "dry_run": True}
        )
        check = str(conn.execute("pragma integrity_check").fetchone()[0])
        summary = {
            "schema_version": "1.0.0-tgb-delayed-disclosure-summary",
            "user_id": args.user_id,
            "media_database": str(media_path),
            "source_contract": {
                "original_images_unchanged": True,
                "ocr_absence_is_not_mask_evidence": True,
                "machine_auto_confirmation": False,
                "claims_and_reviews_are_append_only": True,
            },
            "claim_import": claim_result,
            "review_import": review_result,
            "coverage": coverage,
            "dry_run": bool(args.dry_run),
            "sqlite_integrity": check,
            "green": bool(
                check == "ok"
                and claim_result["rejected"] == 0
                and review_result["rejected"] == 0
                and (args.dry_run or coverage.get("source_changed_claims") == 0)
            ),
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
        description="记录淘股吧打码持仓在后续卖出公开后的追加式身份关系"
    )
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--media-db", required=True)
    parser.add_argument("--claims-manifest", default="")
    parser.add_argument("--reviews-manifest", default="")
    parser.add_argument("--summary", default="")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
