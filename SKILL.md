---
name: taoguba-crawler
description: Archive athlete competition disclosures and broker screenshots, or crawl author posts. This skill should be used when the user asks to "crawl taoguba", "crawl tgb", "scrape taoguba articles", "run the crawler", "crawl bbs", "crawl home page", "generate article HTML", or needs to run the Taoguba (tgb.cn) web crawlers.
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

作者回帖目录在 100 字处可能截断，后续配图也可能缺少标记。回查目标作者的楼层或回复详情，再把原图纳入来源索引。本人回帖入口见 `scripts/tgb_user_replies.py --help`，发帖媒体用 `scripts/tgb_author_images.py --help`。

完整选手档案应检查作者主帖、本人回帖和个人实盘比赛栏目。

### 实盘比赛与逐日报单

从 `/user/blog/myspmath?userID=<账号ID>` 进入各场战绩页，保存逐日持仓申报和收益明细，再从可见的“查看”入口向前、向后翻完报单相册。有些日期只有收益和图片。源数据写入作者案例目录。

```bash
python scripts/tgb_match_reports.py --user-id "$USER_ID" --output-dir "$MATCH_DIR"
```

`MATCH_DIR` 指向本次快照的案例目录。只查询赛事列表时加 `--stage index`。如果同日参加多场比赛，保留每场来源，按日对照持仓、资产和收益；报单申报与券商成交分别核实。字段、空相册、可见性和离线验收见[比赛采集规则](references/competition-reports.md)。

### 券商截图转录

比赛归档中的券商图走[持仓截图转录](skills/tgb-position-screenshot-transcription/SKILL.md)的比赛批次入口。用 `scripts/tgb_match_transcription.py` 从只读原图库产生按 SHA 复核的队列，并按赛事、归属日、提交时间保留每个出处。


发帖图库中的原图通过 `scripts/tgb_transaction_slips.py` 进入逐图识别与审阅。识别需要 Pillow。网页比赛表需要 Node.js、Playwright 和 Chrome。

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
