from __future__ import annotations

from dataclasses import dataclass
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup


BASE_URL = "https://www.tgb.cn"


@dataclass(frozen=True)
class BbsIndexRecord:
    slug: str
    url: str
    title: str
    author: str
    author_id: str
    reply_count: int
    view_count: int
    last_reply_time: str
    post_time: str
    source_page: int
    source_url: str

    def to_legacy_article(self) -> dict[str, str]:
        return {
            "title": self.title,
            "url": self.url,
            "href": f"a/{self.slug}",
        }


@dataclass(frozen=True)
class BbsPagination:
    current_page: int
    total_pages: int
    flag: int
    latest_url: str
    last_url: str


def build_bbs_page_url(page_no: int, flag: int = 1) -> str:
    return f"{BASE_URL}/bbs/{page_no}/{flag}"


def parse_bbs_pagination(html: str, source_url: str = "") -> BbsPagination:
    current_page = _source_page_from_url(source_url) or 1
    flag = _source_flag_from_url(source_url) or 1
    candidates = [int(value) for value in re.findall(r"gotoPage\(\s*\d+\s*,\s*\d+\s*,\s*(\d+)\s*\)", html)]
    candidates.extend(int(value) for value in re.findall(r"pageNo\s*>\s*(\d+)", html))
    candidates.extend(int(value) for value in re.findall(r"pageNo\s*>\s*(\d+)", html))
    candidates.extend(int(value) for value in re.findall(r"pageNo\s*<\s*1\s*\|\|\s*pageNo\s*>\s*(\d+)", html))
    total_pages = max(candidates) if candidates else current_page
    return BbsPagination(
        current_page=current_page,
        total_pages=total_pages,
        flag=flag,
        latest_url=build_bbs_page_url(1, flag),
        last_url=build_bbs_page_url(total_pages, flag),
    )


def parse_bbs_list(html: str, source_url: str = "", source_page: int = 0) -> list[BbsIndexRecord]:
    soup = BeautifulSoup(html, "html.parser")
    records: list[BbsIndexRecord] = []

    for title_link in soup.select('a[href^="a/"], a[href^="/a/"]'):
        href = title_link.get("href", "").strip()
        slug = _extract_slug(href)
        if not slug:
            continue

        row = _find_listing_row(title_link)
        if row is None:
            continue
        if _looks_like_sidebar_or_reward_row(row):
            continue

        title = _clean_title(title_link.get("title") or title_link.get_text(" ", strip=True))
        if not title:
            continue

        author_link = row.select_one('a[href^="blog/"], a[href^="/blog/"]')
        if author_link is None:
            continue

        counts_text = _first_matching_text(row, r"\d+\s*/\s*\d+")
        reply_count, view_count = _parse_counts(counts_text)

        times = re.findall(r"\d{2}-\d{2}\s+\d{2}:\d{2}", row.get_text(" ", strip=True))
        last_reply_time = times[0] if times else ""
        post_time = times[-1] if times else ""

        records.append(
            BbsIndexRecord(
                slug=slug,
                url=urljoin(BASE_URL + "/", f"a/{slug}"),
                title=title,
                author=author_link.get_text(" ", strip=True),
                author_id=_extract_author_id(author_link.get("href", "")),
                reply_count=reply_count,
                view_count=view_count,
                last_reply_time=last_reply_time,
                post_time=post_time,
                source_page=source_page,
                source_url=source_url,
            )
        )

    return _dedupe(records)


def _find_listing_row(title_link):
    node = title_link
    for _ in range(8):
        node = node.parent
        if node is None:
            return None
        text = node.get_text(" ", strip=True)
        if re.search(r"\d+\s*/\s*\d+", text) and re.search(r"\d{2}-\d{2}\s+\d{2}:\d{2}", text):
            return node
    return None


def _looks_like_sidebar_or_reward_row(row) -> bool:
    text = row.get_text(" ", strip=True)
    if "打赏" in text or "积分" in text:
        return True
    return len(row.select('a[href^="a/"], a[href^="/a/"]')) > 1


def _extract_slug(href: str) -> str:
    match = re.search(r"/?a/([^/?#]+)", href)
    return match.group(1) if match else ""


def _extract_author_id(href: str) -> str:
    match = re.search(r"/?blog/(\d+)", href)
    return match.group(1) if match else ""


def _source_page_from_url(url: str) -> int:
    match = re.search(r"/bbs/(\d+)/", url)
    return int(match.group(1)) if match else 0


def _source_flag_from_url(url: str) -> int:
    match = re.search(r"/bbs/\d+/(\d+)", url)
    return int(match.group(1)) if match else 0


def _clean_title(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _first_matching_text(row, pattern: str) -> str:
    regex = re.compile(pattern)
    for node in row.find_all(True):
        text = node.get_text(" ", strip=True)
        if regex.fullmatch(text):
            return text
    match = regex.search(row.get_text(" ", strip=True))
    return match.group(0) if match else ""


def _parse_counts(text: str) -> tuple[int, int]:
    match = re.search(r"(\d+)\s*/\s*(\d+)", text or "")
    if not match:
        return 0, 0
    return int(match.group(1)), int(match.group(2))


def _dedupe(records: list[BbsIndexRecord]) -> list[BbsIndexRecord]:
    seen: set[str] = set()
    unique: list[BbsIndexRecord] = []
    for record in records:
        if record.slug in seen:
            continue
        seen.add(record.slug)
        unique.append(record)
    return unique
