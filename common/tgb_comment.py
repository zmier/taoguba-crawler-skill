from __future__ import annotations

from dataclasses import dataclass
import re

from bs4 import BeautifulSoup


BASE_URL = "https://www.tgb.cn"


@dataclass(frozen=True)
class CommentRecord:
    article_slug: str
    page_no: int
    reply_id: str
    user_id: str
    username: str
    is_author: bool
    floor_label: str
    created_at: str
    text: str
    html: str
    image_urls: list[str]


def build_comment_page_url(slug: str, page_no: int) -> str:
    if page_no <= 1:
        return f"{BASE_URL}/a/{slug}"
    return f"{BASE_URL}/a/{slug}-{page_no}"


def parse_comments(html: str, article_slug: str = "", page_no: int = 1) -> list[CommentRecord]:
    soup = BeautifulSoup(html, "html.parser")
    comments: list[CommentRecord] = []
    for block in soup.select(".comment-data"):
        text_node = block.select_one(".comment-data-text")
        if text_node is None:
            continue
        reply_id = _reply_id(text_node, block)
        user_link = block.select_one(".comment-data-user a.user-name")
        comments.append(
            CommentRecord(
                article_slug=article_slug,
                page_no=page_no,
                reply_id=reply_id,
                user_id=block.get("ustr", "") or _user_id_from_block_id(block.get("id", "")),
                username=_text(user_link),
                is_author=_is_author(block),
                floor_label=_floor_label(block),
                created_at=_created_at(block),
                text=_text(text_node),
                html=str(text_node),
                image_urls=_image_urls(text_node),
            )
        )
    return comments


def _reply_id(text_node, block) -> str:
    match = re.search(r"reply(\d+)", text_node.get("id", ""))
    if match:
        return match.group(1)
    match = re.search(r"reply_\d+_(\d+)", block.get("id", ""))
    return match.group(1) if match else ""


def _user_id_from_block_id(value: str) -> str:
    match = re.search(r"reply_(\d+)_", value)
    return match.group(1) if match else ""


def _text(node) -> str:
    if node is None:
        return ""
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()


def _is_author(block) -> bool:
    user = block.select_one(".comment-data-user")
    return "楼主" in _text(user)


def _created_at(block) -> str:
    node = block.select_one(".pcyclspan")
    match = re.search(r"\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}", _text(node))
    return match.group(0) if match else ""


def _floor_label(block) -> str:
    button = block.select_one(".comment-data-button span.left")
    text = _text(button)
    if not text:
        return ""
    return text.split("·", 1)[0].strip()


def _image_urls(node) -> list[str]:
    urls: list[str] = []
    for img in node.select("img"):
        src = img.get("data-original") or img.get("src2") or img.get("src")
        if not src or "face/" in src:
            continue
        urls.append(src)
    return urls
