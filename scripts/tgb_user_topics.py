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
from common.tgb_user_topics import (
    AuthorArchiveAuthenticationError,
    UserTopicsConfig,
    run_user_topics,
)
from scripts.crawler_bbs import get_headers


def main() -> None:
    parser = argparse.ArgumentParser(description="抓取淘股吧指定用户最新主帖列表")
    parser.add_argument("--user-id", required=True, help="淘股吧用户 ID，例如 252069")
    parser.add_argument("--db", default="", help="SQLite 输出路径，默认 data/tgb-user-{user_id}.sqlite")
    parser.add_argument("--all", action="store_true", help="抓取该用户 moreTopic 当前全部分页")
    parser.add_argument(
        "--author-archive",
        action="store_true",
        help="全量主贴+全文+全部评论分页，但只保存user_id等于目标账号的回复",
    )
    parser.add_argument("--start-page", type=int, default=1)
    parser.add_argument("--end-page", type=int, default=0, help="结束页，0 表示自动使用末页")
    parser.add_argument("--max-pages", type=int, default=0, help="最多抓取多少个列表页；0 表示按 --all/默认逻辑")
    parser.add_argument(
        "--details-only",
        action="store_true",
        help="不重扫列表页，续抓未请求或被旧done/fetched状态掩盖的空正文详情",
    )
    parser.add_argument("--fetch-details", action="store_true", help="额外抓取帖子正文和评论")
    parser.add_argument("--max-articles", type=int, default=20, help="本次最多抓取多少篇帖子详情")
    parser.add_argument("--all-details", action="store_true", help="本次续抓队列中的全部帖子详情")
    parser.add_argument("--comment-pages", type=int, default=1, help="每篇最多抓取多少页评论")
    parser.add_argument("--all-comment-pages", action="store_true", help="按每帖页面报告值抓取全部评论分页")
    parser.add_argument(
        "--skip-comments",
        action="store_true",
        help="只抓认证主贴正文；作者全部回复应由tgb_user_replies.py补齐",
    )
    parser.add_argument("--author-comments-only", action="store_true", help="只将目标user_id的回复写入SQLite")
    parser.add_argument(
        "--manual-approval",
        action="store_true",
        help="确认执行--author-archive全量网络任务；分批模式无需此开关",
    )
    parser.add_argument("--interval", type=float, default=1.0, help="请求间隔秒数")
    args = parser.parse_args()
    if args.skip_comments and args.all_comment_pages:
        parser.error("--skip-comments conflicts with --all-comment-pages")
    if (args.author_archive or args.all_details) and not args.manual_approval:
        parser.error(
            "--author-archive/--all-details requires --manual-approval after 1+5 article pilots"
        )

    load_env_file()
    session = requests.Session()
    session.headers.update(get_headers())
    session.headers.update({"Referer": f"https://www.tgb.cn/blog/{args.user_id}"})

    def fetch_html(url: str) -> str:
        response = session.get(url, timeout=20)
        response.raise_for_status()
        if "/a/" in url and "/user/generalUserCertPage" in response.url:
            raise AuthorArchiveAuthenticationError("author_detail_redirected_to_certification")
        response.encoding = "utf-8"
        return response.text

    db_path = Path(args.db) if args.db else PROJECT_ROOT / "data" / f"tgb-user-{args.user_id}.sqlite"
    max_pages = args.max_pages if args.max_pages > 0 else (None if args.all or args.author_archive else 1)
    fetch_details = args.fetch_details or args.details_only or args.author_archive
    max_article_details = None if args.all_details or args.author_archive else args.max_articles
    summary = run_user_topics(
        UserTopicsConfig(
            db_path=db_path,
            user_id=args.user_id,
            start_page=args.start_page,
            end_page=args.end_page or None,
            max_pages=max_pages,
            details_only=args.details_only,
            fetch_article_details=fetch_details,
            max_article_details=max_article_details if fetch_details else 0,
            comment_pages_per_article=args.comment_pages,
            all_comment_pages=args.all_comment_pages or args.author_archive,
            skip_comments=args.skip_comments,
            author_comments_only=args.author_comments_only or args.author_archive,
            request_interval_seconds=args.interval,
        ),
        fetch_html=fetch_html,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
