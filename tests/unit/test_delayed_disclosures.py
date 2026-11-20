from __future__ import annotations

import base64
from datetime import datetime, timedelta
import hashlib
from pathlib import Path
import sqlite3

from scripts.tgb_delayed_disclosures import (
    append_reviews,
    claim_status_counts,
    evaluate_claim,
    import_claims,
    init_schema,
)


def _strong_claim(source_sha: str, disclosure_sha: str) -> dict[str, object]:
    return {
        "trading_day_gap": 1,
        "candidate_set_size": 1,
        "portfolio_continuity_visually_confirmed": True,
        "source": {
            "document_id": "doc-before",
            "content_sha256": source_sha,
            "statement_time": "2020-06-02T15:00:00+08:00",
            "account_key": "上海证券|***9999",
            "anonymous_active_rows": 1,
            "cumulative_profit_loss": 499836.56,
            "source_mask_visually_confirmed": True,
            "original_image_sha_verified": True,
            "locator": {"visual_row": 1},
        },
        "disclosure": {
            "document_id": "doc-after",
            "content_sha256": disclosure_sha,
            "statement_time": "2020-06-03T11:30:00+08:00",
            "account_key": "上海证券|***9999",
            "stock_name": "容大感光",
            "stock_code": "",
            "holding_quantity": 0,
            "available_quantity": 0,
            "cumulative_profit_loss": 465855.18,
            "daily_profit_loss": -33864.00,
            "revealed_closed_rows": 1,
            "public_name_visually_confirmed": True,
            "zero_position_visually_confirmed": True,
            "original_image_sha_verified": True,
            "locator": {"visual_row": 3},
        },
    }


def _database(path: Path) -> tuple[sqlite3.Connection, str, str]:
    before = b"source-masked-position-image"
    after = b"later-public-sale-image"
    before_sha = hashlib.sha256(before).hexdigest()
    after_sha = hashlib.sha256(after).hexdigest()
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        create table image_assets (
          content_sha256 text primary key,
          base64_data text not null
        );
        create table transaction_slip_documents (
          document_id text primary key,
          author_id text not null,
          source_record_id text not null,
          source_url text not null,
          content_sha256 text not null,
          broker_name_ocr text not null,
          account_label_masked text not null,
          document_type text not null
        );
        """
    )
    conn.executemany(
        "insert into image_assets values (?,?)",
        [
            (before_sha, base64.b64encode(before).decode()),
            (after_sha, base64.b64encode(after).decode()),
        ],
    )
    conn.executemany(
        "insert into transaction_slip_documents values (?,?,?,?,?,?,?,?)",
        [
            (
                "doc-before",
                "1116585",
                "comment:topic:1",
                "https://image.tgb.cn/before",
                before_sha,
                "上海证券",
                "***9999",
                "position_snapshot",
            ),
            (
                "doc-after",
                "1116585",
                "comment:topic:2",
                "https://image.tgb.cn/after",
                after_sha,
                "上海证券",
                "***9999",
                "position_snapshot",
            ),
        ],
    )
    init_schema(conn)
    return conn, before_sha, after_sha


def test_strong_candidate_scores_but_never_auto_confirms():
    result = evaluate_claim(_strong_claim("a" * 64, "b" * 64))
    assert result["score"] == 98
    assert result["machine_state"] == "machine-strong-candidate"
    assert result["auto_confirmed"] is False
    assert round(result["profit_loss_residual"], 2) == 117.38
    assert round(result["profit_loss_residual_ratio"], 6) == 0.003466


def test_hard_rejections_override_score():
    claim = _strong_claim("a" * 64, "b" * 64)
    claim["source"]["account_key"] = "长城证券|***2659"
    result = evaluate_claim(claim)
    assert result["machine_state"] == "unresolved"
    assert "account_mismatch_or_missing" in result["hard_rejections"]

    claim = _strong_claim("a" * 64, "b" * 64)
    claim["source"]["anonymous_active_rows"] = 4
    claim["disclosure"]["revealed_closed_rows"] = 2
    result = evaluate_claim(claim)
    assert result["machine_state"] == "unresolved"
    assert "ambiguous_or_missing_anonymous_active_row" in result["hard_rejections"]

    claim = _strong_claim("a" * 64, "b" * 64)
    claim["disclosure"]["holding_quantity"] = 100
    result = evaluate_claim(claim)
    assert result["machine_state"] == "unresolved"
    assert "disclosed_position_not_zero" in result["hard_rejections"]


def test_claim_import_is_idempotent_and_review_is_append_only(tmp_path: Path):
    conn, before_sha, after_sha = _database(tmp_path / "media.sqlite")
    try:
        source_counts = (
            conn.execute("select count(*) from image_assets").fetchone()[0],
            conn.execute("select count(*) from transaction_slip_documents").fetchone()[0],
        )
        claim = _strong_claim(before_sha, after_sha)
        first = import_claims(conn, author_id="1116585", claims=[claim])
        assert first["imported"] == 1
        assert first["rejected"] == 0
        item = first["items"][0]
        assert item["machine_state"] == "machine-strong-candidate"

        second = import_claims(conn, author_id="1116585", claims=[claim])
        assert second["duplicates"] == 1
        assert conn.execute(
            "select count(*) from transaction_slip_identity_claims"
        ).fetchone()[0] == 1
        assert conn.execute(
            "select count(*) from transaction_slip_identity_claim_reviews"
        ).fetchone()[0] == 1

        machine_reviewed_at = conn.execute(
            """
            select reviewed_at
            from transaction_slip_identity_claim_reviews
            where claim_id=? and state='candidate'
            order by reviewed_at desc, rowid desc
            limit 1
            """,
            (item["claim_id"],),
        ).fetchone()[0]
        manual_reviewed_at = (
            datetime.fromisoformat(machine_reviewed_at.replace("Z", "+00:00"))
            + timedelta(seconds=1)
        ).isoformat()

        review = {
            "claim_id": item["claim_id"],
            "state": "human-confirmed",
            "reviewed_by": "fixture-reviewer",
            "reviewed_at": manual_reviewed_at,
            "review_note": "目视核对前后原图、唯一持仓、零持仓与盈亏连续性。",
            "expected_basis_sha256": item["basis_sha256"],
        }
        reviewed = append_reviews(
            conn, author_id="1116585", reviews=[review]
        )
        assert reviewed["appended"] == 1
        repeated = append_reviews(
            conn, author_id="1116585", reviews=[review]
        )
        assert repeated["duplicates"] == 1
        counts = claim_status_counts(conn, "1116585")
        assert counts["latest_review_state_counts"] == {"human-confirmed": 1}
        assert counts["source_changed_claims"] == 0
        assert source_counts == (
            conn.execute("select count(*) from image_assets").fetchone()[0],
            conn.execute("select count(*) from transaction_slip_documents").fetchone()[0],
        )
    finally:
        conn.close()


def test_source_hash_drift_blocks_confirmation(tmp_path: Path):
    conn, before_sha, after_sha = _database(tmp_path / "media.sqlite")
    try:
        imported = import_claims(
            conn,
            author_id="1116585",
            claims=[_strong_claim(before_sha, after_sha)],
        )
        item = imported["items"][0]
        conn.execute(
            "update transaction_slip_documents set content_sha256=? where document_id='doc-before'",
            ("f" * 64,),
        )
        conn.commit()
        review = {
            "claim_id": item["claim_id"],
            "state": "human-confirmed",
            "reviewed_by": "fixture-reviewer",
            "reviewed_at": "2026-08-26T17:00:00+08:00",
            "review_note": "不应在来源漂移后确认。",
            "expected_basis_sha256": item["basis_sha256"],
        }
        result = append_reviews(conn, author_id="1116585", reviews=[review])
        assert result["rejected"] == 1
        assert "source_changed_cannot_confirm" in result["errors"][0]
        assert claim_status_counts(conn, "1116585")["source_changed_claims"] == 1
    finally:
        conn.close()
