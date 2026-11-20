#!/usr/bin/env python3
"""Derive searchable trading-slip OCR and rows from the author media archive.

The content-addressed image asset remains canonical. OCR, classification and
parsed fields are explicitly draft derivatives and never rewrite source rows.
"""

from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
from typing import Any, Iterable

from PIL import Image, ImageOps


PROJECT_ROOT = Path(__file__).resolve().parents[1]
VISION_SOURCE = Path(__file__).with_name("tgb_vision_ocr.swift")
PARSER_VERSION = "1.0.0-tgb-transaction-slip-parser"
IMAGE_MARKER = "［图片］"

SUMMARY_LABELS = {
    "total_assets": ("总资产",),
    "total_profit_loss": ("总盈亏",),
    "total_market_value": ("总市值",),
    "withdrawable_cash": ("可取",),
    "available_cash": ("可用",),
}
STRONG_MARKERS = (
    "总资产",
    "总盈亏",
    "总市值",
    "持仓/可用",
    "成本/现价",
    "成交日期",
    "成交数量",
    "成交价格",
    "发生金额",
    "证券代码",
)
WEAK_MARKERS = (
    "A股交易",
    "实盘交易",
    "人民币账户",
    "持仓",
    "市值",
    "盈亏",
    "买入",
    "买人",
    "卖出",
    "撤单",
    "查询",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def stable_document_id(
    author_id: str,
    article_slug: str,
    content_kind: str,
    reply_id: str,
    image_position: int,
) -> str:
    raw = "|".join(
        (author_id, article_slug, content_kind, reply_id, str(image_position))
    )
    return "tgb-slip-" + sha256_text(raw)[:24]


def init_ocr_schema(conn: sqlite3.Connection) -> None:
    conn.execute("pragma foreign_keys=on")
    conn.executescript(
        """
        create table if not exists transaction_slip_ocr_assets (
          content_sha256 text primary key,
          ocr_engine text not null,
          ocr_engine_version text not null,
          ocr_languages text not null,
          preprocess_profile text not null,
          raw_ocr_text text not null,
          raw_ocr_sha256 text not null,
          ocr_lines_json text not null,
          mean_confidence real,
          classification text not null,
          classification_score real not null,
          classification_basis_json text not null,
          ocr_status text not null,
          ocr_error text not null default '',
          ocr_at text not null,
          foreign key(content_sha256) references image_assets(content_sha256)
        );

        """
    )


def init_schema(conn: sqlite3.Connection) -> None:
    init_ocr_schema(conn)
    conn.executescript(
        """
        create table if not exists transaction_slip_documents (
          document_id text primary key,
          author_id text not null,
          article_slug text not null,
          content_kind text not null,
          reply_id text not null default '',
          image_position integer not null,
          source_record_id text not null,
          source_url text not null,
          content_sha256 text not null,
          source_created_at text not null default '',
          statement_date text not null default '',
          date_source text not null default '',
          document_type text not null,
          broker_name_ocr text not null default '',
          account_label_present integer not null default 0,
          account_label_masked text not null default '',
          currency text not null default 'CNY',
          total_assets real,
          total_profit_loss real,
          total_market_value real,
          withdrawable_cash real,
          available_cash real,
          document_fields_json text not null default '{}',
          parse_status text not null,
          review_state text not null,
          reviewed_at text not null default '',
          reviewed_by text not null default '',
          review_note text not null default '',
          parser_version text not null,
          created_at text not null,
          updated_at text not null,
          unique(author_id,article_slug,content_kind,reply_id,image_position),
          foreign key(content_sha256) references image_assets(content_sha256),
          foreign key(content_sha256) references transaction_slip_ocr_assets(content_sha256)
        );

        create table if not exists transaction_slip_rows (
          document_id text not null,
          row_no integer not null,
          row_type text not null,
          trade_date text not null default '',
          trade_time text not null default '',
          stock_code text not null default '',
          stock_name text not null default '',
          side text not null default '',
          quantity real,
          available_quantity real,
          trade_price real,
          cost_price real,
          current_price real,
          transaction_amount real,
          market_value real,
          profit_loss real,
          profit_loss_pct real,
          commission real,
          stamp_duty real,
          transfer_fee real,
          other_fee real,
          cash_balance real,
          raw_row_text text not null,
          values_json text not null default '{}',
          field_sources_json text not null default '{}',
          parse_confidence real not null,
          review_state text not null,
          reviewed_at text not null default '',
          reviewed_by text not null default '',
          review_note text not null default '',
          parser_version text not null,
          primary key(document_id,row_no),
          foreign key(document_id) references transaction_slip_documents(document_id)
            on delete cascade
        );

        create index if not exists idx_transaction_slip_ocr_classification
          on transaction_slip_ocr_assets(classification,ocr_status);
        create index if not exists idx_transaction_slip_documents_author_date
          on transaction_slip_documents(author_id,statement_date,document_type);
        create index if not exists idx_transaction_slip_documents_asset
          on transaction_slip_documents(content_sha256);
        create index if not exists idx_transaction_slip_rows_type_stock
          on transaction_slip_rows(row_type,stock_code,stock_name);
        """
    )
    for table in ("transaction_slip_documents", "transaction_slip_rows"):
        existing = {str(row[1]) for row in conn.execute(f"pragma table_info({table})")}
        for column in ("reviewed_at", "reviewed_by", "review_note"):
            if column not in existing:
                conn.execute(
                    f"alter table {table} add column {column} text not null default ''"
                )
    conn.commit()


def normalize_text(lines: Iterable[dict[str, Any]]) -> str:
    return "\n".join(
        str(line.get("text", "")).strip()
        for line in lines
        if str(line.get("text", "")).strip()
    )


def classify_ocr(raw_text: str) -> tuple[str, float, list[str]]:
    compact = re.sub(r"\s+", "", raw_text)
    strong = [marker for marker in STRONG_MARKERS if marker in compact]
    weak = [marker for marker in WEAK_MARKERS if marker in compact]
    basis = [f"strong:{marker}" for marker in strong] + [
        f"weak:{marker}" for marker in weak
    ]
    score = min(1.0, len(strong) * 0.22 + len(weak) * 0.07)
    trade_headers = tuple(
        marker
        for marker in (
            "成交日期", "成交时间", "证券代码", "证券名称",
            "成交数量", "成交均价", "成交金额", "发生金额",
        )
        if marker in compact
    )
    order_headers = tuple(
        marker
        for marker in (
            "委托时间", "委托数量", "委托/成交", "全部成交", "全部撤单",
        )
        if marker in compact
    )
    basis.extend(f"trade-header:{marker}" for marker in trade_headers)
    basis.extend(f"order-header:{marker}" for marker in order_headers)
    if len(trade_headers) >= 3:
        return "trade_ledger", max(score, 0.75), basis
    if "委托时间" in order_headers and len(order_headers) >= 2:
        return "order_history", max(score, 0.75), basis
    if (
        any(marker in compact for marker in ("总资产", "总市值", "持仓/可用", "成本/现价"))
        or len(strong) >= 2
        or (len(strong) >= 1 and len(weak) >= 3)
    ):
        return "position_snapshot", max(score, 0.70), basis
    if len(strong) == 0 and len(weak) <= 1 and len(compact) >= 20:
        return "non_slip", max(0.65, 1.0 - score), basis
    return "unknown", max(0.20, score), basis


def _number(text: str) -> float | None:
    normalized = re.sub(r"(?<=\d)[:：](?=\d)", ".", text.strip())
    match = re.fullmatch(r"[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?%?", normalized)
    if not match:
        return None
    value = normalized.replace(",", "")
    if value.endswith("%"):
        value = value[:-1]
    try:
        return float(value)
    except ValueError:
        return None


def _center_x(line: dict[str, Any]) -> float:
    return float(line.get("x", 0)) + float(line.get("width", 0)) / 2


def _find_line(lines: list[dict[str, Any]], aliases: Iterable[str]) -> dict[str, Any] | None:
    for line in lines:
        compact = re.sub(r"\s+", "", str(line.get("text", "")))
        if any(alias in compact for alias in aliases):
            return line
    return None


def parse_summary_fields(
    lines: list[dict[str, Any]],
) -> tuple[dict[str, float | None], dict[str, dict[str, Any]]]:
    values: dict[str, float | None] = {name: None for name in SUMMARY_LABELS}
    sources: dict[str, dict[str, Any]] = {}
    numeric = [line for line in lines if _number(str(line.get("text", ""))) is not None]
    for field, aliases in SUMMARY_LABELS.items():
        label = _find_line(lines, aliases)
        if label is None:
            continue
        label_x = _center_x(label)
        label_y = float(label.get("y", 0))
        candidates = [
            line
            for line in numeric
            if 0 < float(line.get("y", 0)) - label_y < 0.09
            and abs(_center_x(line) - label_x) < 0.18
        ]
        if not candidates:
            continue
        chosen = min(
            candidates,
            key=lambda line: (
                float(line.get("y", 0)) - label_y,
                abs(_center_x(line) - label_x),
            ),
        )
        values[field] = _number(str(chosen.get("text", "")))
        sources[field] = {
            "label": label.get("text", ""),
            "value_text": chosen.get("text", ""),
            "label_confidence": label.get("confidence"),
            "value_confidence": chosen.get("confidence"),
            "source": "vision-layout-nearest-value-above-label",
        }
    return values, sources


def mask_account_label(raw_text: str) -> tuple[str, bool, str]:
    compact_lines = [re.sub(r"\s+", "", line) for line in raw_text.splitlines()]
    for line in compact_lines:
        if "证券" not in line and "账户" not in line:
            continue
        match = re.search(r"([\u4e00-\u9fff]{2,8}证券)?[^\d]*(\d{4,})", line)
        if not match:
            continue
        broker = (match.group(1) or "").strip()
        digits = match.group(2)
        return broker, True, "***" + digits[-4:]
    return "", False, ""


def _column_values(
    lines: list[dict[str, Any]], y: float, tolerance: float = 0.018
) -> dict[str, tuple[float, dict[str, Any]]]:
    found: dict[str, tuple[float, dict[str, Any]]] = {}
    for line in lines:
        value = _number(str(line.get("text", "")))
        if value is None or abs(float(line.get("y", 0)) - y) > tolerance:
            continue
        x = _center_x(line)
        column = "market" if x < 0.31 else "pnl" if x < 0.58 else "qty" if x < 0.80 else "price"
        found[column] = (value, line)
    return found


def parse_position_rows(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    header = _find_line(lines, ("持仓/可用", "成本/现价"))
    if header is None:
        return []
    header_y = float(header.get("y", 0))
    excluded = {
        "市值", "盈亏", "持仓", "可用", "成本", "现价",
        "买入", "买人", "卖出", "撤单", "查询", "总资产", "总盈亏", "总市值",
    }
    names = []
    for line in lines:
        text = str(line.get("text", "")).strip()
        y = float(line.get("y", 0))
        if not (0.025 < header_y - y < 0.35) or _center_x(line) >= 0.31:
            continue
        if not re.fullmatch(r"[\u4e00-\u9fffA-Za-z*STst]{2,12}", text):
            continue
        if any(token in text for token in excluded):
            continue
        names.append(line)
    rows: list[dict[str, Any]] = []
    for line in sorted(names, key=lambda item: float(item.get("y", 0)), reverse=True):
        primary_y = float(line.get("y", 0))
        primary = _column_values(lines, primary_y)
        secondary_candidates = sorted(
            {
                float(item.get("y", 0))
                for item in lines
                if 0.008 < primary_y - float(item.get("y", 0)) < 0.055
                and _number(str(item.get("text", ""))) is not None
            },
            reverse=True,
        )
        secondary_y = secondary_candidates[0] if secondary_candidates else None
        secondary = _column_values(lines, secondary_y) if secondary_y is not None else {}
        contributing = [line]
        contributing.extend(item[1] for item in primary.values())
        contributing.extend(item[1] for item in secondary.values())
        raw = " | ".join(
            str(item.get("text", ""))
            for item in sorted(
                {id(item): item for item in contributing}.values(),
                key=lambda item: (-float(item.get("y", 0)), float(item.get("x", 0))),
            )
        )
        confidences = [float(item.get("confidence", 0)) for item in contributing]
        rows.append(
            {
                "row_type": "position",
                "stock_name": str(line.get("text", "")),
                "quantity": primary.get("qty", (None, {}))[0],
                "available_quantity": secondary.get("qty", (None, {}))[0],
                "cost_price": primary.get("price", (None, {}))[0],
                "current_price": secondary.get("price", (None, {}))[0],
                "market_value": secondary.get("market", (None, {}))[0],
                "profit_loss": primary.get("pnl", (None, {}))[0],
                "profit_loss_pct": secondary.get("pnl", (None, {}))[0],
                "raw_row_text": raw,
                "values_json": json.dumps(
                    {
                        "primary": {key: value[0] for key, value in primary.items()},
                        "secondary": {key: value[0] for key, value in secondary.items()},
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                "field_sources_json": json.dumps(
                    {"source": "vision-layout-position-table", "header": header.get("text", "")},
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                "parse_confidence": sum(confidences) / len(confidences) if confidences else 0.0,
            }
        )
    return rows


def compile_vision_helper(output: Path) -> tuple[str, str]:
    swiftc = shutil.which("swiftc")
    if not swiftc or not VISION_SOURCE.exists():
        raise RuntimeError("apple_vision_swift_toolchain_missing")
    subprocess.run(
        [swiftc, str(VISION_SOURCE), "-framework", "Vision", "-framework", "AppKit", "-o", str(output)],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    version = subprocess.run(
        [swiftc, "--version"], check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    ).stdout.splitlines()[0]
    return str(output), version


def vision_ocr(binary: str, image_bytes: bytes, temp_dir: Path) -> list[dict[str, Any]]:
    suffix = ".png"
    with Image.open(io.BytesIO(image_bytes)) as image:
        image = ImageOps.exif_transpose(image).convert("RGB")
        path = temp_dir / (hashlib.sha256(image_bytes).hexdigest() + suffix)
        image.save(path, format="PNG")
    try:
        result = subprocess.run(
            [binary, str(path)],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=90,
        )
        payload = json.loads(result.stdout)
        if not isinstance(payload, list):
            raise RuntimeError("vision_ocr_result_not_list")
        return payload
    finally:
        path.unlink(missing_ok=True)


def tesseract_ocr(image_bytes: bytes, *, binary: str) -> tuple[list[dict[str, Any]], str]:
    with Image.open(io.BytesIO(image_bytes)) as image:
        image = ImageOps.exif_transpose(image).convert("L")
        image = ImageOps.autocontrast(image)
        image = image.resize((image.width * 3, image.height * 3), Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
    version = subprocess.run(
        [binary, "--version"], check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    ).stdout.splitlines()[0]
    result = subprocess.run(
        [binary, "stdin", "stdout", "-l", "chi_sim+eng", "--psm", "6", "tsv"],
        input=buffer.getvalue(), check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    rows = result.stdout.decode("utf-8", "replace").splitlines()
    if not rows:
        return [], version
    header = rows[0].split("\t")
    lines: list[dict[str, Any]] = []
    for raw in rows[1:]:
        values = raw.split("\t")
        if len(values) != len(header):
            continue
        item = dict(zip(header, values))
        text = item.get("text", "").strip()
        if not text:
            continue
        lines.append(
            {
                "text": text,
                "confidence": max(0.0, float(item.get("conf", "-1"))) / 100.0,
                "x": float(item.get("left", 0)) / max(1, image.width * 3),
                "y": 1.0 - (float(item.get("top", 0)) + float(item.get("height", 0))) / max(1, image.height * 3),
                "width": float(item.get("width", 0)) / max(1, image.width * 3),
                "height": float(item.get("height", 0)) / max(1, image.height * 3),
            }
        )
    return lines, version


def source_metadata(
    canonical: sqlite3.Connection | None,
    reply_feed: sqlite3.Connection | None,
    *,
    article_slug: str,
    content_kind: str,
    reply_id: str,
) -> tuple[str, str]:
    if content_kind == "main_post" and canonical is not None:
        row = canonical.execute(
            "select post_time from articles where slug=?", (article_slug,)
        ).fetchone()
        return (row[0] if row else "", f"article:{article_slug}")
    if reply_id and canonical is not None:
        row = canonical.execute(
            "select created_at from comments where article_slug=? and reply_id=?",
            (article_slug, reply_id),
        ).fetchone()
        if row:
            return row[0], f"comment:{article_slug}:{reply_id}"
    if reply_id and reply_feed is not None:
        row = reply_feed.execute(
            "select reply_created_at from user_reply_feed_items where article_slug=? and reply_id=?",
            (article_slug, reply_id),
        ).fetchone()
        if row:
            return row[0], f"reply-feed:{article_slug}:{reply_id}"
    return "", f"unknown:{article_slug}:{reply_id}"


def upsert_asset_ocr(
    conn: sqlite3.Connection,
    *,
    content_sha256: str,
    engine: str,
    version: str,
    lines: list[dict[str, Any]],
    error: str = "",
) -> None:
    raw_text = normalize_text(lines)
    classification, score, basis = classify_ocr(raw_text)
    confidences = [float(line.get("confidence", 0)) for line in lines]
    with conn:
        conn.execute(
            """
            insert into transaction_slip_ocr_assets (
              content_sha256,ocr_engine,ocr_engine_version,ocr_languages,
              preprocess_profile,raw_ocr_text,raw_ocr_sha256,ocr_lines_json,
              mean_confidence,classification,classification_score,
              classification_basis_json,ocr_status,ocr_error,ocr_at
            ) values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            on conflict(content_sha256) do update set
              ocr_engine=excluded.ocr_engine,
              ocr_engine_version=excluded.ocr_engine_version,
              ocr_languages=excluded.ocr_languages,
              preprocess_profile=excluded.preprocess_profile,
              raw_ocr_text=excluded.raw_ocr_text,
              raw_ocr_sha256=excluded.raw_ocr_sha256,
              ocr_lines_json=excluded.ocr_lines_json,
              mean_confidence=excluded.mean_confidence,
              classification=excluded.classification,
              classification_score=excluded.classification_score,
              classification_basis_json=excluded.classification_basis_json,
              ocr_status=excluded.ocr_status,
              ocr_error=excluded.ocr_error,
              ocr_at=excluded.ocr_at
            """,
            (
                content_sha256, engine, version, "zh-Hans,en-US", "source-image",
                raw_text, sha256_text(raw_text), json.dumps(lines, ensure_ascii=False),
                (sum(confidences) / len(confidences) if confidences else None),
                classification, score, json.dumps(basis, ensure_ascii=False),
                "ok" if not error else "failed", error, utc_now(),
            ),
        )


def reclassify_existing_assets(conn: sqlite3.Connection) -> int:
    """Refresh OCR-derived document classes without running OCR again."""

    rows = conn.execute(
        """
        select content_sha256,raw_ocr_text
        from transaction_slip_ocr_assets
        where ocr_status='ok'
        order by content_sha256
        """
    ).fetchall()
    with conn:
        for row in rows:
            classification, score, basis = classify_ocr(row["raw_ocr_text"])
            conn.execute(
                """
                update transaction_slip_ocr_assets
                set classification=?,classification_score=?,
                    classification_basis_json=?
                where content_sha256=?
                """,
                (
                    classification,
                    score,
                    json.dumps(basis, ensure_ascii=False),
                    row["content_sha256"],
                ),
            )
    return len(rows)


def upsert_documents(
    conn: sqlite3.Connection,
    *,
    author_id: str,
    canonical: sqlite3.Connection | None,
    reply_feed: sqlite3.Connection | None,
) -> int:
    rows = conn.execute(
        """
        select l.*,a.raw_ocr_text,a.ocr_lines_json,a.classification
        from content_image_links l
        join transaction_slip_ocr_assets a on a.content_sha256=l.content_sha256
        where l.author_id=? and l.content_sha256 is not null
        order by l.article_slug,l.content_kind,l.reply_id,l.position
        """,
        (author_id,),
    ).fetchall()
    now = utc_now()
    with conn:
        for link in rows:
            lines = json.loads(link["ocr_lines_json"])
            summary, summary_sources = parse_summary_fields(lines)
            position_rows = (
                parse_position_rows(lines)
                if link["classification"] == "position_snapshot"
                else []
            )
            broker, account_present, account_masked = mask_account_label(
                link["raw_ocr_text"]
            )
            created_at, source_record_id = source_metadata(
                canonical,
                reply_feed,
                article_slug=link["article_slug"],
                content_kind=link["content_kind"],
                reply_id=link["reply_id"],
            )
            date_source = "reply_or_post_created_at" if created_at else ""
            if not created_at:
                url_date = re.search(
                    r"/img/(\d{4})/(\d{2})/(\d{2})/", link["source_url"]
                )
                if url_date:
                    created_at = "-".join(url_date.groups())
                    date_source = "image_url_path"
            statement_date = created_at[:10] if re.match(r"\d{4}-\d{2}-\d{2}", created_at) else ""
            doc_id = stable_document_id(
                author_id, link["article_slug"], link["content_kind"],
                link["reply_id"], int(link["position"]),
            )
            parsed_values = [value for value in summary.values() if value is not None]
            parse_status = (
                "not-a-slip"
                if link["classification"] == "non_slip"
                else "parse-partial"
                if parsed_values or position_rows
                else "ocr-only"
            )
            review_state = (
                "not-a-slip" if link["classification"] == "non_slip" else "ocr-draft"
            )
            conn.execute(
                """
                insert into transaction_slip_documents (
                  document_id,author_id,article_slug,content_kind,reply_id,
                  image_position,source_record_id,source_url,content_sha256,
                  source_created_at,statement_date,date_source,document_type,
                  broker_name_ocr,account_label_present,account_label_masked,
                  currency,total_assets,total_profit_loss,total_market_value,
                  withdrawable_cash,available_cash,document_fields_json,
                  parse_status,review_state,parser_version,created_at,updated_at
                ) values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                on conflict(document_id) do update set
                  source_record_id=excluded.source_record_id,
                  source_url=excluded.source_url,
                  content_sha256=excluded.content_sha256,
                  source_created_at=excluded.source_created_at,
                  statement_date=excluded.statement_date,
                  date_source=excluded.date_source,
                  document_type=excluded.document_type,
                  broker_name_ocr=excluded.broker_name_ocr,
                  account_label_present=excluded.account_label_present,
                  account_label_masked=excluded.account_label_masked,
                  total_assets=excluded.total_assets,
                  total_profit_loss=excluded.total_profit_loss,
                  total_market_value=excluded.total_market_value,
                  withdrawable_cash=excluded.withdrawable_cash,
                  available_cash=excluded.available_cash,
                  document_fields_json=excluded.document_fields_json,
                  parse_status=excluded.parse_status,
                  parser_version=excluded.parser_version,
                  updated_at=excluded.updated_at
                """,
                (
                    doc_id, author_id, link["article_slug"], link["content_kind"],
                    link["reply_id"], int(link["position"]), source_record_id,
                    link["source_url"], link["content_sha256"], created_at,
                    statement_date, date_source if statement_date else "",
                    link["classification"], broker, int(account_present), account_masked,
                    "CNY", summary["total_assets"], summary["total_profit_loss"],
                    summary["total_market_value"], summary["withdrawable_cash"],
                    summary["available_cash"], json.dumps(summary_sources, ensure_ascii=False),
                    parse_status, review_state, PARSER_VERSION, now, now,
                ),
            )
            previous_reviews = {
                int(row["row_no"]): dict(row)
                for row in conn.execute(
                    """
                    select row_no,raw_row_text,review_state,reviewed_at,reviewed_by,review_note
                    from transaction_slip_rows where document_id=?
                    """,
                    (doc_id,),
                ).fetchall()
            }
            conn.execute("delete from transaction_slip_rows where document_id=?", (doc_id,))
            for row_no, parsed in enumerate(position_rows, start=1):
                prior = previous_reviews.get(row_no, {})
                preserve_review = bool(
                    prior
                    and prior.get("raw_row_text") == parsed["raw_row_text"]
                    and prior.get("review_state") == "human-checked"
                )
                conn.execute(
                    """
                    insert into transaction_slip_rows (
                      document_id,row_no,row_type,stock_name,quantity,
                      available_quantity,cost_price,current_price,market_value,
                      profit_loss,profit_loss_pct,raw_row_text,values_json,
                      field_sources_json,parse_confidence,review_state,
                      reviewed_at,reviewed_by,review_note,parser_version
                    ) values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        doc_id,row_no,parsed["row_type"],parsed["stock_name"],
                        parsed["quantity"],parsed["available_quantity"],
                        parsed["cost_price"],parsed["current_price"],
                        parsed["market_value"],parsed["profit_loss"],
                        parsed["profit_loss_pct"],parsed["raw_row_text"],
                        parsed["values_json"],parsed["field_sources_json"],
                        parsed["parse_confidence"],
                        "human-checked" if preserve_review else "ocr-draft",
                        prior.get("reviewed_at", "") if preserve_review else "",
                        prior.get("reviewed_by", "") if preserve_review else "",
                        prior.get("review_note", "") if preserve_review else "",
                        PARSER_VERSION,
                    ),
                )
    return len(rows)


def ocr_asset_batch(conn, assets, args, planned):
    if planned == 0:
        return 0, 0, 0, {}
    attempted = succeeded = failed = 0
    errors: dict[str, int] = {}
    with TemporaryDirectory(prefix="tgb-slip-ocr-") as temp_name:
        temp_dir = Path(temp_name)
        engine = args.engine
        vision_binary = version = ""
        if engine in {"auto", "vision"}:
            try:
                vision_binary, version = compile_vision_helper(temp_dir / "tgb_vision_ocr")
                engine = "apple-vision"
            except Exception:
                if args.engine == "vision":
                    raise
                engine = "tesseract"
        tesseract_binary = args.tesseract_binary or shutil.which("tesseract") or ""
        if engine == "tesseract" and not tesseract_binary:
            raise RuntimeError("tesseract_binary_missing")
        for index, asset in enumerate(assets, start=1):
            attempted += 1
            try:
                image_bytes = base64.b64decode(asset["base64_data"], validate=True)
                if engine == "apple-vision":
                    lines = vision_ocr(vision_binary, image_bytes, temp_dir)
                    engine_version = version
                else:
                    lines, engine_version = tesseract_ocr(
                        image_bytes, binary=tesseract_binary
                    )
                upsert_asset_ocr(
                    conn, content_sha256=asset["content_sha256"], engine=engine,
                    version=engine_version, lines=lines,
                )
                succeeded += 1
            except Exception as error:
                failed += 1
                key = f"{type(error).__name__}:{error}"
                errors[key] = errors.get(key, 0) + 1
                upsert_asset_ocr(
                    conn, content_sha256=asset["content_sha256"], engine=engine,
                    version=version, lines=[], error=key,
                )
            if index == 1 or index % 25 == 0 or index == planned:
                print(json.dumps({"stage":"tgb_transaction_slip_ocr","attempted":index,"planned":planned,"succeeded":succeeded,"failed":failed},ensure_ascii=False),flush=True)
    return attempted, succeeded, failed, errors


def run(args: argparse.Namespace) -> dict[str, Any]:
    media_path = Path(args.media_db).expanduser().resolve()
    canonical_path = Path(args.canonical_db).expanduser().resolve() if args.canonical_db else None
    reply_path = Path(args.reply_feed_db).expanduser().resolve() if args.reply_feed_db else None
    if not media_path.exists():
        raise FileNotFoundError(f"media_database_missing:{media_path}")
    conn = sqlite3.connect(media_path)
    conn.row_factory = sqlite3.Row
    canonical = sqlite3.connect(canonical_path) if canonical_path and canonical_path.exists() else None
    reply_feed = sqlite3.connect(reply_path) if reply_path and reply_path.exists() else None
    init_schema(conn)
    reclassified = 0
    try:
        query = """
          select a.content_sha256,a.base64_data
          from image_assets a
          left join transaction_slip_ocr_assets o on o.content_sha256=a.content_sha256
          where (?=1 or o.content_sha256 is null)
          order by a.content_sha256
        """
        assets = conn.execute(query, (1 if args.force else 0,)).fetchall()
        if args.max_assets > 0:
            assets = assets[: args.max_assets]
        if args.reclassify_only:
            assets = []
            reclassified = reclassify_existing_assets(conn)
        attempted, succeeded, failed, errors = ocr_asset_batch(conn, assets, args, len(assets))
        documents = upsert_documents(
            conn, author_id=args.user_id, canonical=canonical, reply_feed=reply_feed
        )
        totals = {
            "downloaded_assets": conn.execute("select count(*) from image_assets").fetchone()[0],
            "ocr_assets": conn.execute("select count(*) from transaction_slip_ocr_assets where ocr_status='ok'").fetchone()[0],
            "ocr_failures": conn.execute("select count(*) from transaction_slip_ocr_assets where ocr_status<>'ok'").fetchone()[0],
            "documents": conn.execute("select count(*) from transaction_slip_documents where author_id=?",(args.user_id,)).fetchone()[0],
            "candidate_documents": conn.execute("select count(*) from transaction_slip_documents where author_id=? and document_type not in ('non_slip','unknown')",(args.user_id,)).fetchone()[0],
            "unknown_documents": conn.execute("select count(*) from transaction_slip_documents where author_id=? and document_type='unknown'",(args.user_id,)).fetchone()[0],
            "position_rows": conn.execute("select count(*) from transaction_slip_rows where row_type='position'").fetchone()[0],
            "pending_image_sources": conn.execute("select count(*) from image_sources where status='pending'").fetchone()[0],
            "unresolved_image_failures": conn.execute("select count(*) from image_download_failures where resolved_at='' ").fetchone()[0],
        }
        summary = {
            "schema_version": "1.0.0-tgb-transaction-slip-derivation",
            "user_id": args.user_id,
            "media_database": str(media_path),
            "source_contract": {
                "original_base64_assets_unchanged": True,
                "ocr_is_derived_draft": True,
                "structured_fields_are_nullable_and_reviewable": True,
                "full_account_identity_reconstructed": False,
            },
            "run": {"attempted":attempted,"succeeded":succeeded,"failed":failed,"reclassified":reclassified,"errors":errors,"documents_upserted":documents},
            "coverage": totals,
            "sqlite_integrity": conn.execute("pragma integrity_check").fetchone()[0],
            "green": bool(totals["downloaded_assets"] == totals["ocr_assets"] and totals["ocr_failures"] == 0 and totals["pending_image_sources"] == 0 and totals["unresolved_image_failures"] == 0),
            "retrieved_at": utc_now(),
        }
    finally:
        if canonical is not None:
            canonical.close()
        if reply_feed is not None:
            reply_feed.close()
        conn.close()
    if args.summary:
        summary_path = Path(args.summary).expanduser().resolve()
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="OCR并结构化淘股吧作者媒体库中的交割单/持仓截图")
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--media-db", required=True)
    parser.add_argument("--canonical-db", default="")
    parser.add_argument("--reply-feed-db", default="")
    parser.add_argument("--summary", default="")
    parser.add_argument("--engine", choices=("auto","vision","tesseract"), default="auto")
    parser.add_argument(
        "--reclassify-only", action="store_true",
        help="Reuse stored OCR text, refresh classifications/documents, and skip OCR",
    )
    parser.add_argument("--tesseract-binary", default="")
    parser.add_argument("--max-assets", type=int, default=0)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
