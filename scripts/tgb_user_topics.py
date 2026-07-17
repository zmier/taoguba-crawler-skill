#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app_common import load_env_file
from common.tgb_user_topics import UserTopicsConfig, run_user_topics
from scripts.crawler_bbs import get_headers


def main() -> None:
    parser = argparse.ArgumentParser(description="抓取淘股吧指定用户最新主帖列表")
    parser.add_argument("--user-id", required=True, help="淘股吧用户 ID，例如 252069")
    parser.add_argument("--db", default="", help="SQLite 输出路径，默认 data/tgb-user-{user_id}.sqlite")
    parser.add_argument("--all", action="store_true", help="抓取该用户 moreTopic 当前全部分页")
    parser.add_argument("--start-page", type=int, default=1)
    parser.add_argument("--end-page", type=int, default=0, help="结束页，0 表示自动使用末页")
    parser.add_argument("--max-pages", type=int, default=0, help="最多抓取多少个列表页；0 表示按 --all/默认逻辑")
    parser.add_argument("--details-only", action="store_true", help="不重扫列表页，直接从现有数据库续抓缺失详情")
    parser.add_argument("--fetch-details", action="store_true", help="额外抓取帖子正文和评论")
    parser.add_argument("--max-articles", type=int, default=20, help="本次最多抓取多少篇帖子详情")
    parser.add_argument("--comment-pages", type=int, default=1, help="每篇最多抓取多少页评论")
    parser.add_argument("--interval", type=float, default=1.0, help="请求间隔秒数")
    args = parser.parse_args()

    load_env_file()
    session = requests.Session()
    session.headers.update(get_headers())
    session.headers.update({"Referer": f"https://www.tgb.cn/blog/{args.user_id}"})

    def fetch_html(url: str) -> str:
        response = session.get(url, timeout=20)
        response.raise_for_status()
        response.encoding = "utf-8"
        return response.text

    db_path = Path(args.db) if args.db else PROJECT_ROOT / "data" / f"tgb-user-{args.user_id}.sqlite"
    max_pages = args.max_pages if args.max_pages > 0 else (None if args.all else 1)
    fetch_details = args.fetch_details or args.details_only
    summary = run_user_topics(
        UserTopicsConfig(
            db_path=db_path,
            user_id=args.user_id,
            start_page=args.start_page,
            end_page=args.end_page or None,
            max_pages=max_pages,
            details_only=args.details_only,
            fetch_article_details=fetch_details,
            max_article_details=args.max_articles if fetch_details else 0,
            comment_pages_per_article=args.comment_pages,
            request_interval_seconds=args.interval,
        ),
        fetch_html=fetch_html,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
