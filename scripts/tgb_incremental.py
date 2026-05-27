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
from common.tgb_incremental import IncrementalConfig, run_incremental
from scripts.crawler_bbs import get_headers


def main() -> None:
    parser = argparse.ArgumentParser(description="运行淘股吧 incremental 增量模式")
    parser.add_argument("--db", default=str(PROJECT_ROOT / "data" / "tgb-incremental.sqlite"))
    parser.add_argument("--max-pages", type=int, default=5)
    parser.add_argument("--max-articles", type=int, default=20)
    parser.add_argument("--max-refresh-articles", type=int, default=20)
    parser.add_argument("--comment-pages", type=int, default=1)
    parser.add_argument("--interval", type=float, default=0.8)
    args = parser.parse_args()

    load_env_file()
    session = requests.Session()
    session.headers.update(get_headers())

    def fetch_html(url: str) -> str:
        response = session.get(url, timeout=20)
        response.raise_for_status()
        response.encoding = "utf-8"
        return response.text

    summary = run_incremental(
        IncrementalConfig(
            db_path=Path(args.db),
            max_pages=args.max_pages,
            max_article_details=args.max_articles,
            max_refresh_articles=args.max_refresh_articles,
            comment_pages_per_article=args.comment_pages,
            request_interval_seconds=args.interval,
        ),
        fetch_html=fetch_html,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
