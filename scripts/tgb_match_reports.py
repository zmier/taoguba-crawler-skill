#!/usr/bin/env python3
"""Archive one TGB athlete's competition reports into a case-owned snapshot."""

import argparse
import base64
import fcntl
import hashlib
import json
import re
import sqlite3
import subprocess
import sys
import time
from collections import Counter
from contextlib import ExitStack, closing
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app_common import load_env_file
from common import tgb_match_reports as mr
from scripts.crawler_bbs import get_headers
from scripts.tgb_author_images import download_image


def bind(out, uid):
    """Adopt a historical case only if its directory links and source receipt agree."""
    binding = out / "账号.json"
    if binding.exists():
        if mr.read_json(binding).get("author_id") != uid:
            raise ValueError("此快照目录属于其他作者")
        return
    existing = {p.name for p in out.iterdir()} - {".比赛采集.lock"}
    if existing:
        cards = mr.read_json(out / mr.CARDS)
        receipt = mr.read_json(out / mr.AUDIT)
        if not cards or receipt.get("author_id") != uid:
            raise ValueError("已有目录缺少可核对的作者身份")
        for card in cards:
            mr.match_id(card["url"], uid)
    mr.write_json(binding, {"author_id": uid})


def get_groups(site, uid, seq, date, direction, interval):
    params = {"spmatchSeq": seq, "lookUserID": uid, "dateNum": date}
    if direction:
        params["direction"] = direction
    time.sleep(interval)
    response = site.get(
        mr.ORIGIN + "/spmatch/gains/listUrl", params=params, timeout=20, allow_redirects=False
    )
    if response.status_code != 200:
        raise RuntimeError(f"相册 HTTP {response.status_code}，未完成读取")
    return mr.gallery_groups(response.json())


def collect_tables(out, uid, username, cards, interval):
    content = json.dumps(
        dict(
            uid=uid,
            username=username,
            cookie=get_headers().get("Cookie", ""),
            cards=cards,
            interval=interval,
        )
    )
    raw = (
        subprocess.check_output(
            ["node", str(ROOT / "scripts/tgb_match_tables.cjs")], input=content, text=True
        )
        if cards
        else "[]"
    )
    tables = json.loads(raw)
    mr.dates_and_tables(uid, cards, tables)
    mr.write_json(out / mr.TABLES, tables)


def collect_nav(out, uid, site, buttons, locked, interval):
    start = {}
    for seq, date in sorted(buttons):
        start[seq] = date
    trace = {}
    for seq, date in start.items():

        def fetch(anchor, direction):
            entries = get_groups(site, uid, seq, anchor, direction, interval)
            for entry in entries:
                if (seq, entry["day"]) in locked:
                    entry["urls"] = []
            return entries

        trace[seq] = mr.walk(date, fetch)
    mr.navigation_links(trace, buttons)
    mr.write_json(out / mr.NAV, trace)


def connect_cache(path):
    db = sqlite3.connect(path)
    db.execute("pragma foreign_keys=ON")
    db.executescript("""
        create table if not exists galleries(match_id text, report_day text, links_json text,
            primary key(match_id,report_day));
        create table if not exists files(sha256 text primary key,byte_size integer,mime text,base64_data text);
        create table if not exists sources(url text primary key,sha256 text references files(sha256));
    """)
    return db


def get_image(db, cdn, url, offline, interval):
    mr.verify_url(url)
    row = db.execute("select sha256 from sources where url=?", (url,)).fetchone()
    if row:
        return row[0]
    if offline:
        raise ValueError("离线缓存缺少此原图")
    time.sleep(interval)
    image = download_image(cdn, url, timeout=20, max_bytes=25 * 1024 * 1024)
    with db:
        db.execute(
            "insert or ignore into files values(?,?,?,?)",
            (image.content_sha256, len(image.content), image.mime_type, image.base64_data),
        )
        db.execute("insert into sources values(?,?)", (url, image.content_sha256))
    return image.content_sha256


def archive(out, uid, tables, rows, nav, site, cdn, offline, interval):
    holdings, incomes, buttons, locked = rows
    neighbors = mr.navigation_links(nav, buttons)
    keys = sorted((buttons | neighbors.keys()) - locked)
    if offline and not (out / mr.MEDIA).exists() and keys:
        raise ValueError("离线回放缺少比赛原图库")
    # Keep other visible table layouts as source evidence until their columns and image entries are mapped.
    unmapped_tabs = [
        [m["seq"], "交割单"]
        for m in tables
        if any(len(page) > 1 for page in m["tables"].get("交割单", []))
    ]
    issues = []
    empty = []
    pictures = []
    with closing(connect_cache(out / mr.MEDIA)) as db:
        for seq, day in keys:
            key = seq, day
            row = db.execute(
                "select links_json from galleries where match_id=? and report_day=?", key
            ).fetchone()
            if row:
                links = json.loads(row[0])
            elif key in buttons:
                if offline:
                    raise ValueError(f"离线缓存缺少相册 {seq}/{day}")
                groups = get_groups(site, uid, seq, day, None, interval)
                if any(group["day"] != day for group in groups):
                    raise ValueError(f"相册日期不符 {seq}/{day}")
                links = [[g["submitted"], i, url] for g in groups for i, url in enumerate(g["urls"], 1)]
            else:
                links = []
            links.extend(item for item in neighbors.get(key, []) if item not in links)
            if not offline:
                with db:
                    db.execute(
                        "insert or replace into galleries values(?,?,?)",
                        (*key, json.dumps(links, ensure_ascii=False)),
                    )
            if not links:
                empty.append(key)
            for submitted, ordinal, url in links:
                try:
                    sha = get_image(db, cdn, url, offline, interval)
                except (requests.RequestException, RuntimeError, ValueError) as error:
                    sha = ""
                    issues.append([seq, day, url, type(error).__name__, str(error)])
                pictures.append([seq, day, submitted, ordinal, url, sha])
        if (
            db.execute("pragma integrity_check").fetchone() != ("ok",)
            or db.execute("pragma foreign_key_check").fetchone()
        ):
            raise ValueError("比赛原图库完整性检查失败")
        hashes = {r[-1] for r in pictures if r[-1]}
        verified = set()
        for sha, size, encoded in db.execute("select sha256,byte_size,base64_data from files"):
            raw = base64.b64decode(encoded, validate=True)
            if len(raw) != size or hashlib.sha256(raw).hexdigest() != sha:
                raise ValueError("原图字节或哈希不符")
            verified.add(sha)
        if not hashes <= verified:
            raise ValueError("原图引用悬空")
    matches = []
    for m in tables:
        seq = m["seq"]
        h = [r for r in holdings if r[0] == seq]
        i = [r for r in incomes if r[0] == seq]
        imgs = [r for r in pictures if r[0] == seq]
        hdays = {r[3] for r in h}
        idays = {r[3] for r in i}
        pdays = {r[1] for r in imgs if r[-1]}
        matches.append(
            dict(
                seq=seq,
                holding_rows=len(h),
                holding_dates=len(hdays),
                income_dates=len(idays),
                income_period=[min(idays), max(idays)] if idays else [],
                holding_period=[min(hdays), max(hdays)] if hdays else [],
                stock_row_types=dict(Counter(r[7] for r in h)),
                with_num=sum(r[8] not in ("--", "**", "") for r in h),
                image_buttons=sum(s == seq for s, _ in buttons),
                extra_gallery_dates=sum((seq, d) not in buttons for d in pdays),
                image_dates=len(pdays),
                images=len(imgs),
                income_days_without_holding_rows=sorted(idays - hdays),
                income_days_without_images=sorted(idays - pdays),
                visible_tabs=list(m["tables"]),
                gallery_status="双向已到站点终点" if seq in nav else "无可见查看入口",
            )
        )
    audit = dict(
        author_id=uid,
        matches=matches,
        issues=issues,
        unmapped_tabs=unmapped_tabs,
        unique_income_dates=len({r[3] for r in incomes}),
        potential_galleries=len(keys),
        gallery_count=len(keys),
        empty_galleries=len(empty),
        empty_gallery_dates=empty,
        locked_dates=sorted(locked),
        gallery_nav_verified=bool(nav),
        placements=len(pictures),
        unique_images=len(hashes),
        acquired_placements=sum(bool(r[-1]) for r in pictures),
        state="partial" if issues or unmapped_tabs else "visible-scope-complete",
    )
    mr.write_csv(out / mr.HOLDINGS, mr.HOLD_HEADER, holdings)
    mr.write_csv(out / mr.INCOME, mr.INCOME_HEADER, incomes)
    mr.write_csv(out / mr.PHOTOS, mr.PHOTO_HEADER, pictures)
    mr.write_json(out / mr.AUDIT, audit)
    print(
        json.dumps(
            {
                k: audit[k]
                for k in ("author_id", "state", "unique_income_dates", "placements", "unique_images")
            },
            ensure_ascii=False,
        )
    )
    return 2 if issues or unmapped_tabs else 0


def run(uid, out, stage, username=None, interval=0.5):
    if not re.fullmatch("[0-9]+", uid) or not 0 <= interval <= 60:
        raise ValueError("作者 ID 或请求间隔无效")
    out.mkdir(parents=True, exist_ok=True)
    with ExitStack() as stack:
        lock = stack.enter_context((out / ".比赛采集.lock").open("a"))
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        bind(out, uid)
        site = stack.enter_context(requests.Session())
        cdn = stack.enter_context(requests.Session())
        cdn.headers["Referer"] = mr.ORIGIN + "/"
        if stage != "replay":
            load_env_file()
            site.headers.update(get_headers())
        if stage in ("all", "index", "tables") and not (out / mr.CARDS).exists():
            response = site.get(
                mr.ORIGIN + "/user/blog/myspmath",
                params={"userID": uid},
                timeout=20,
                allow_redirects=False,
            )
            if response.status_code != 200:
                raise RuntimeError(f"比赛目录 HTTP {response.status_code}")
            mr.write_json(out / mr.CARDS, mr.parse_directory(response.content.decode("utf-8"), uid))
        cards = mr.read_json(out / mr.CARDS)
        for card in cards:
            mr.match_id(card["url"], uid)
        if stage == "index":
            print(f"{uid}: {len(cards)} 场可见赛事")
            return 0
        if stage in ("all", "tables") and not (out / mr.TABLES).exists():
            collect_tables(out, uid, username, cards, interval)
        tables = mr.read_json(out / mr.TABLES)
        if username and any(
            m.get("athlete", username) != username or username not in m["summary"] for m in tables
        ):
            raise ValueError("表格昵称与预期不符")
        rows = mr.dates_and_tables(uid, cards, tables)
        if stage == "tables":
            return 0
        if stage in ("all", "galleries") and not (out / mr.NAV).exists():
            collect_nav(out, uid, site, rows[2], rows[3], interval)
        nav = mr.read_json(out / mr.NAV)
        if stage == "galleries":
            mr.navigation_links(nav, rows[2])
            return 0
        return archive(out, uid, tables, rows, nav, site, cdn, stage == "replay", interval)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--expected-username")
    parser.add_argument(
        "--stage", choices=["all", "index", "tables", "galleries", "archive", "replay"], default="all"
    )
    parser.add_argument("--interval", type=float, default=0.5)
    args = parser.parse_args()
    return run(args.user_id, args.output_dir, args.stage, args.expected_username, args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
