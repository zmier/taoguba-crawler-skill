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
from common.tgb_full import FullRunConfig, run_full_batch
from common.tgb_index import build_bbs_page_url, parse_bbs_pagination
from scripts.crawler_bbs import get_headers


def main() -> None:
    parser = argparse.ArgumentParser(description="运行淘股吧 TASK10 full production batch")
    parser.add_argument("--db", default=str(PROJECT_ROOT / "data" / "tgb-full.sqlite"))
    parser.add_argument("--total-pages", type=int, default=0)
    parser.add_argument("--start-page", type=int, default=0)
    parser.add_argument("--end-page", type=int, default=1)
    parser.add_argument("--max-list-pages", type=int, default=1)
    parser.add_argument("--max-articles-per-page", type=int, default=70)
    parser.add_argument("--max-comment-pages", type=int, default=3)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--manual-approval", action="store_true")
    args = parser.parse_args()
    if not args.manual_approval:
        raise SystemExit("TASK10 requires --manual-approval")

    load_env_file()
    session = requests.Session()
    session.headers.update(get_headers())

    def fetch_html(url: str) -> str:
        response = session.get(url, timeout=20)
        response.raise_for_status()
        response.encoding = "utf-8"
        return response.text

    total_pages = args.total_pages or _fetch_total_pages(fetch_html)
    start_page = args.start_page or total_pages
    summary = run_full_batch(
        FullRunConfig(
            db_path=Path(args.db),
            total_pages=total_pages,
            start_page=start_page,
            end_page=args.end_page,
            max_list_pages_per_run=args.max_list_pages,
            max_articles_per_page=args.max_articles_per_page,
            max_comment_pages_per_article=args.max_comment_pages,
            request_interval_seconds=args.interval,
            production_full=True,
            manual_approval=True,
        ),
        fetch_html=fetch_html,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def _fetch_total_pages(fetch_html) -> int:
    latest_url = build_bbs_page_url(1, 1)
    html = fetch_html(latest_url)
    return parse_bbs_pagination(html, source_url=latest_url).total_pages


if __name__ == "__main__":
    main()
