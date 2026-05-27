from __future__ import annotations

from dataclasses import dataclass
import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup


@dataclass(frozen=True)
class ArticleDetail:
    slug: str
    url: str
    topic_id: str
    title: str
    author: str
    author_id: str
    view_count: int
    comment_count: int
    comment_page_count: int
    main_text: str
    main_html: str
    image_urls: list[str]


def parse_article_detail(html: str, url: str = "") -> ArticleDetail:
    soup = BeautifulSoup(html, "html.parser")
    main = soup.select_one("#first") or soup.select_one(".article-text.p_coten")
    gio = soup.select_one("#gioMsg")
    author_container = soup.select_one("#authorUserid")

    view_count, comment_count = _parse_view_and_comment_counts(soup)
    comment_page_count = _parse_comment_page_count(soup, comment_count)

    return ArticleDetail(
        slug=_slug_from_url(url),
        url=url,
        topic_id=_first_match(html, r"var\s+topicTopicID\s*=\s*(\d+)") or "",
        title=_text(soup.select_one("#stockTitle") or soup.select_one(".article-tittle")),
        author=(gio.get("username") if gio else "") or _author_from_sidebar(soup),
        author_id=(gio.get("userid") if gio else "") or (author_container.get("userattr") if author_container else ""),
        view_count=view_count,
        comment_count=comment_count,
        comment_page_count=comment_page_count,
        main_text=_text(main),
        main_html=str(main) if main else "",
        image_urls=_image_urls(main),
    )


def _slug_from_url(url: str) -> str:
    path = urlparse(url).path
    match = re.search(r"/a/([^/?#-]+)", path)
    return match.group(1) if match else ""


def _text(node) -> str:
    if node is None:
        return ""
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()


def _first_match(text: str, pattern: str) -> str:
    match = re.search(pattern, text)
    return match.group(1) if match else ""


def _parse_view_and_comment_counts(soup: BeautifulSoup) -> tuple[int, int]:
    text = soup.get_text(" ", strip=True)
    view = _int_after_label(text, "浏览")
    comment = _int_after_label(text, "评论")
    return view, comment


def _int_after_label(text: str, label: str) -> int:
    match = re.search(label + r"\s*([\d,]+)", text)
    return int(match.group(1).replace(",", "")) if match else 0


def _parse_comment_page_count(soup: BeautifulSoup, comment_count: int) -> int:
    text = soup.get_text(" ", strip=True)
    candidates = [int(value) for value in re.findall(r"pageNo>\s*(\d+)|pageNo\s*>\s*(\d+)", text) for value in value if value]
    candidates.extend(int(value) for value in re.findall(r"页\s*/\s*(\d+)", text))
    if candidates:
        return max(candidates)
    if comment_count <= 0:
        return 1
    return max(1, (comment_count + 49) // 50)


def _author_from_sidebar(soup: BeautifulSoup) -> str:
    author_link = soup.select_one('.right-data-user a[href^="/blog/"]')
    return _text(author_link)


def _image_urls(node) -> list[str]:
    if node is None:
        return []
    urls: list[str] = []
    for img in node.select("img"):
        src = img.get("data-original") or img.get("src2") or img.get("src")
        if not src or src.endswith(".gif") or "face/" in src:
            continue
        urls.append(src)
    return urls
