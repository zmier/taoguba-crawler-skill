---
name: taoguba-crawler
description: This skill should be used when the user asks to "crawl taoguba", "crawl tgb", "scrape taoguba articles", "run the crawler", "crawl bbs", "crawl home page", "generate article HTML", or needs to run the Taoguba (tgb.cn) web crawlers.
version: 0.1.0
allowed-tools: Bash, Read
---

# Taoguba Crawler

This skill runs the Taoguba (tgb.cn) article crawlers located in the project root.

## Prerequisites

- Python 3 with `requests`, `beautifulsoup4`, `python-dotenv` installed
- A `.env` file in the project root containing `COOKIE` and optionally `USER_AGENT`

## Available Crawlers

### 1. BBS Crawler (`crawler_bbs.py`)

Crawl the forum board at `tgb.cn/bbs/1/1` using HTML scraping.

```bash
python crawler_bbs.py
```

- Extracts article list by parsing `a.overhide.mw300` elements
- Gets each article's main post and author replies
- Downloads images and embeds them as base64 in HTML
- Outputs: `output/bbs_YYYY-MM-DD.json` and `output/bbs_YYYY-MM-DD_HHMMSS.html`

### 2. Home Crawler (`crawler_home.py`)

Crawl the homepage recommendations via JSON API (`/newIndex/getZh`).

```bash
python crawler_home.py
```

- Fetches articles from the JSON API (default 2 pages)
- Same content extraction and HTML generation as BBS crawler
- Outputs: `output/home_YYYY-MM-DD.json` and `output/home_YYYY-MM-DD_HHMMSS.html`

### 3. User Topics Crawler (`tgb_user_topics.py`)

Crawl one user's latest-topic archive, such as:

```text
https://www.tgb.cn/user/blog/moreTopic?userID=252069
```

Recommended first pass:

```bash
python scripts/tgb_user_topics.py --user-id 252069 --all
```

Optional detail pass:

```bash
python scripts/tgb_user_topics.py --user-id 252069 --max-pages 2 --fetch-details --max-articles 5 --comment-pages 1
```

Resume detail backfill from an existing index database:

```bash
python scripts/tgb_user_topics.py --user-id 252069 --details-only --max-articles 200 --comment-pages 1
```

- Extracts topic index records from `user/blog/moreTopic?userID={id}&pageNo={n}`
- Detects total pages from the page's `pageNum`
- Stores data in `data/tgb-user-{user_id}.sqlite`
- Reuses the existing article-detail and comment parsers for `/a/{slug}`
- For large archives, fetch index first and then fetch details in small batches to reduce anti-bot risk; index completion alone is not full-text completion
- `--details-only` resumes missing details from SQLite rows with empty `fetched_at`

## Common Workflow

To run both crawlers:

```bash
python crawler_bbs.py && python crawler_home.py
```

## Key Implementation Details

- **Authentication**: Both scripts read `COOKIE` from `.env` via `python-dotenv`
- **Rate limiting**: 0.5-1s delay between requests to avoid being blocked
- **Image handling**: Images are downloaded and embedded as base64 in the HTML output
- **Article content**: Extracts main post (`#first`) and author replies (`.comment-data` with author badge)
- **Output directory**: All results saved to `output/` folder

## Scripts

The crawler scripts are bundled in `scripts/`:

- **`scripts/crawler_bbs.py`** - BBS forum crawler (HTML scraping)
- **`scripts/crawler_home.py`** - Homepage crawler (JSON API)
- **`scripts/tgb_user_topics.py`** - User latest-topic archive crawler

To run the bundled scripts directly:

```bash
python scripts/crawler_bbs.py
python scripts/crawler_home.py
python scripts/tgb_user_topics.py --user-id 252069 --all
```

## Troubleshooting

- If no articles are returned, check that `.env` contains a valid `COOKIE` value
- If image downloads fail, the HTML will show error messages inline
- Network timeouts default to 10-15 seconds per request
