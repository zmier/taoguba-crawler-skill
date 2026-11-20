"""Prepare a per-SHA Stage A review queue from a read-only competition archive."""

import argparse
import base64
import csv
import hashlib
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import tgb_match_reports as mr
from scripts.tgb_transaction_slips import init_ocr_schema, ocr_asset_batch


def read_placements(root, uid, db):
    audit = mr.read_json(root / mr.AUDIT)
    if audit["author_id"] != uid:
        raise ValueError("比赛归档作者不符")
    matches = {mr.match_id(card["url"], uid) for card in mr.read_json(root / mr.CARDS)}
    galleries = {
        (seq, day, stamp, int(ordinal), url)
        for seq, day, raw in db.execute("select match_id,report_day,links_json from galleries")
        for stamp, ordinal, url in json.loads(raw)
    }
    placements = []
    with (root / mr.PHOTOS).open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != mr.PHOTO_HEADER:
            raise ValueError("比赛图片索引列发生变化")
        for row in reader:
            seq, day, stamp, ordinal, url, digest = (row[k] for k in mr.PHOTO_HEADER)
            key = (seq, mr.day_key(day), stamp, int(ordinal), mr.verify_url(url))
            if seq not in matches or key not in galleries:
                raise ValueError("图片位置与赛事或相册不符")
            galleries.remove(key)
            if digest and db.execute("select sha256 from sources where url=?", (url,)).fetchone() != (
                digest,
            ):
                raise ValueError("原图链接与索引 SHA 不符")
            placements.append((*key, digest or None))
    hashes = {r[-1] for r in placements if r[-1]}
    if galleries or (len(placements), len(hashes)) != (audit["placements"], audit["unique_images"]):
        raise ValueError("比赛图片索引与覆盖回执不一致")
    return placements, hashes


def prepare(root, uid, output, args):
    if output.resolve().is_relative_to(root.resolve()):
        raise ValueError("请把分析库保存在来源目录之外")
    with closing(sqlite3.connect((root / mr.MEDIA).resolve().as_uri() + "?mode=ro", uri=True)) as source:
        source.execute("begin")
        placements, hashes = read_placements(root, uid, source)
        # Bind the derivative to the occurrence set, including delayed uploads and missing images.
        signature = hashlib.sha256(
            json.dumps(sorted(placements), ensure_ascii=False).encode()
        ).hexdigest()
        for digest in sorted(hashes):
            row = source.execute(
                "select byte_size,base64_data from files where sha256=?", (digest,)
            ).fetchone()
            if not row:
                raise ValueError("原图缺失")
            data = base64.b64decode(row[1], validate=True)
            if row[0] != len(data) or hashlib.sha256(data).hexdigest() != digest:
                raise ValueError("原图字节校验失败")
        with closing(sqlite3.connect(output)) as db:
            db.execute("begin immediate")
            tables = {r[0] for r in db.execute("select name from sqlite_master where type='table'")}
            if tables and (
                "match_input" not in tables
                or db.execute("select author_id, index_hash from match_input").fetchall()
                != [(uid, signature)]
            ):
                raise ValueError("输出库已有其他来源或快照，请使用新的分析库")
            with db:
                db.execute(
                    "create table if not exists match_input(author_id text primary key, index_hash text)"
                )
                db.execute("insert or ignore into match_input values(?,?)", (uid, signature))
                db.execute("create table if not exists image_assets(content_sha256 text primary key)")
                db.executemany("insert or ignore into image_assets values(?)", ((h,) for h in hashes))
                db.execute("""create table if not exists match_placements(
                    match_id text, report_day text, submitted_at text, ordinal integer, source_url text,
                    content_sha256 text references image_assets, primary key(match_id, report_day, submitted_at, ordinal, source_url))""")
                db.executemany("insert or ignore into match_placements values(?,?,?,?,?,?)", placements)
            init_ocr_schema(db)
            db.execute("""create view if not exists stage_a_review_queue as
                select a.content_sha256, count(p.source_url) as occurrences, o.ocr_status, o.classification,
                       o.raw_ocr_text, o.ocr_lines_json
                from image_assets a join match_placements p using(content_sha256)
                left join transaction_slip_ocr_assets o using(content_sha256) group by a.content_sha256""")
            reviewed = {
                r[0]
                for r in db.execute(
                    "select content_sha256 from transaction_slip_ocr_assets where ocr_status='ok'"
                )
            }
            pending = sorted(hashes - reviewed)[: args.max_assets]

            # Stream original bytes to OCR. The review database stores no source image bytes.
            def load_asset(digest):
                (encoded,) = source.execute(
                    "select base64_data from files where sha256=?", (digest,)
                ).fetchone()
                return {"content_sha256": digest, "base64_data": encoded}

            ocr_asset_batch(db, (load_asset(digest) for digest in pending), args, len(pending))
            (complete,) = db.execute(
                "select count(*) from transaction_slip_ocr_assets where ocr_status='ok'"
            ).fetchone()
            (failed,) = db.execute(
                "select count(*) from transaction_slip_ocr_assets where ocr_status='failed'"
            ).fetchone()
            print(
                json.dumps(
                    dict(
                        author_id=uid,
                        placements=len(placements),
                        unique_images=len(hashes),
                        missing_placements=sum(r[-1] is None for r in placements),
                        ocr_ok=complete,
                        ocr_failed=failed,
                    ),
                    ensure_ascii=False,
                )
            )
            return 2 if failed else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--match-dir", required=True, type=Path)
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--output-db", required=True, type=Path)
    parser.add_argument("--max-assets", type=int, help="0 只准备审图队列；默认识别全部尚未成功的图片")
    parser.add_argument("--engine", choices=("auto", "vision", "tesseract"), default="auto")
    parser.add_argument("--tesseract-binary", default="")
    args = parser.parse_args()
    if args.max_assets is not None and args.max_assets < 0:
        parser.error("--max-assets 不能为负")
    raise SystemExit(prepare(args.match_dir, args.user_id, args.output_db, args))
