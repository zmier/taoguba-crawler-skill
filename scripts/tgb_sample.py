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
from scripts.crawler_bbs import get_headers
from common.tgb_sample import SampleConfig, run_sample


def main() -> None:
    parser = argparse.ArgumentParser(description="运行淘股吧 sample 小闭环")
    parser.add_argument("--db", default=str(PROJECT_ROOT / "data" / "tgb-sample.sqlite"))
    parser.add_argument("--list-pages", type=int, default=1)
    parser.add_argument("--max-articles", type=int, default=3)
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

    list_urls = [f"https://www.tgb.cn/bbs/{page}/1" for page in range(1, args.list_pages + 1)]
    summary = run_sample(
        SampleConfig(
            db_path=Path(args.db),
            list_urls=list_urls,
            max_articles=args.max_articles,
            comment_pages_per_article=args.comment_pages,
            request_interval_seconds=args.interval,
        ),
        fetch_html=fetch_html,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
