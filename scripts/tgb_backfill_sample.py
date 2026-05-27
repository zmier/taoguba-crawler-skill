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
from common.tgb_backfill import BackfillSampleConfig, run_backfill_sample
from common.tgb_index import build_bbs_page_url, parse_bbs_pagination
from scripts.crawler_bbs import get_headers


def main() -> None:
    parser = argparse.ArgumentParser(description="运行淘股吧 backfill sample")
    parser.add_argument("--db", default=str(PROJECT_ROOT / "data" / "tgb-backfill-sample.sqlite"))
    parser.add_argument("--total-pages", type=int, default=0)
    parser.add_argument("--max-list-pages", type=int, default=2)
    parser.add_argument("--max-articles-per-page", type=int, default=3)
    parser.add_argument("--max-comment-pages", type=int, default=2)
    parser.add_argument("--interval", type=float, default=1.0)
    args = parser.parse_args()

    load_env_file()
    session = requests.Session()
    session.headers.update(get_headers())

    def fetch_html(url: str) -> str:
        response = session.get(url, timeout=20)
        response.raise_for_status()
        response.encoding = "utf-8"
        return response.text

    total_pages = args.total_pages or _fetch_total_pages(fetch_html)
    summary = run_backfill_sample(
        BackfillSampleConfig(
            db_path=Path(args.db),
            total_pages=total_pages,
            max_list_pages=args.max_list_pages,
            max_articles_per_page=args.max_articles_per_page,
            max_comment_pages_per_article=args.max_comment_pages,
            request_interval_seconds=args.interval,
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
