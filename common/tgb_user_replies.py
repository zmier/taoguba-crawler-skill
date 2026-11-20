from __future__ import annotations

from dataclasses import dataclass
import re
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

from bs4 import BeautifulSoup

from common.tgb_comment import CommentRecord


BASE_URL = "https://www.tgb.cn"
LOGIN_PATHS = {"/web/login/index", "/user/generalUserCertPage"}
LOGIN_MARKERS = ("请先登录", "登录可查看全文", "generalUserCertPage")


class UserReplyAuthenticationError(RuntimeError):
    """The authenticated author-reply source is unavailable."""


class UserReplyStructureError(RuntimeError):
    """The reply feed/detail no longer satisfies the validated structure."""


@dataclass(frozen=True)
class UserReplyFeedRecord:
    user_id: str
    username: str
    reply_id: str
    reply_created_at: str
    article_slug: str
    article_title: str
    article_url: str
    reply_url: str
    author_display_text: str
    displayed_char_count: int | None
    like_count: int | None
    avatar_url: str
    source_page: int
    position: int


def build_user_reply_feed_url(user_id: str, anchor_date: str, page_no: int) -> str:
    if not str(user_id).strip():
        raise ValueError("user_id_required")
    if page_no < 1:
        raise ValueError("page_no_must_be_positive")
    query = urlencode(
        {"time": anchor_date, "userID": str(user_id), "pageNo": str(page_no)}
    )
    return f"{BASE_URL}/user/blog/moreReplyMod?{query}"


def build_reply_detail_url(article_slug: str, reply_id: str) -> str:
    slug = str(article_slug).strip()
    resolved_reply_id = str(reply_id).strip()
    if not slug or slug.lower() in {"null", "none"}:
        raise ValueError("reply_detail_article_slug_required")
    if not resolved_reply_id.isdigit():
        raise ValueError("reply_detail_reply_id_must_be_numeric")
    return f"{BASE_URL}/a/{slug}/{resolved_reply_id}"


def strip_third_party_quote(text: str) -> str:
    """Return only the target author's display segment from moreReplyMod.

    The feed appends the replied-to user's body in a ``[quote]`` block.  A
    100-character preview can stop midway through the opening tag, so partial
    ``[q``/``[qu``/… suffixes are removed as well.  The quoted body is never
    target-author text and must not enter the author archive.
    """

    # A quote block can precede or follow the author's own reply.  Remove every
    # complete block while preserving author text on both sides.  Any remaining
    # opening tag is necessarily truncated by the display-feed character cap,
    # so everything after it is untrusted quoted material.
    value = re.sub(
        r"\[quote\].*?\[/quote\]", "", text or "", flags=re.IGNORECASE | re.DOTALL
    )
    value = re.sub(r"\[quote.*$", "", value, flags=re.IGNORECASE | re.DOTALL)
    return re.sub(
        r"\[(?:q(?:u(?:o(?:t(?:e)?)?)?)?)?$", "", value, flags=re.IGNORECASE
    ).rstrip()


def normalize_author_text(text: str) -> str:
    value = strip_third_party_quote(text)
    value = value.replace("[淘股吧]", "").replace("[引用原文已无法访问]", "")
    # Direct reply pages can retain TGB stock-link presentation wrappers while
    # moreReplyMod exposes only the wrapped stock name.  Remove the wrappers
    # for identity comparison without rewriting the archived author prose.
    value = re.sub(r"(?i)\[/?gubar\]", "", value)
    value = value.replace("[查看战绩]", "查看战绩")
    value = re.sub(r"[［\[]表情:\d+[］\]]", "", value)
    value = re.sub(r"[［\[]图片(?:[］\]])?", "", value)
    value = re.sub(r"[［\[]图(?:片)?(?:[］\]])?$", "", value)
    value = re.sub(r"[［\[]$", "", value)
    value = value.replace("\xa0", " ").replace("@", "")
    value = re.sub(r"(?i)(?:sh|sz)(?=\d{6}(?:\D|$))", "", value)
    # Some feed rows expose a decoded HTML-entity tail (``gt;``/``lt;``)
    # while the direct detail text omits that presentation token.
    value = re.sub(r"(?i)&?(?:gt|lt);", "", value)
    # The account reply directory can terminate a 100-char preview at a raw
    # entity/continuation boundary represented only by a trailing ampersand.
    value = re.sub(r"&+$", "", value)
    # Historical moreReplyMod rows can cut a raw ``&nbsp;`` token into a
    # visible trailing ``nb``/``nbs`` fragment at the display cap.
    value = re.sub(r"(?i)(?:\s|&)+(?:nb|nbs|nbsp;?)$", "", value)
    return re.sub(r"\s+", "", value).strip()


def clean_author_full_text(text: str) -> str:
    """Remove only known TGB presentation markers from stored author prose."""

    value = strip_third_party_quote(text or "")
    value = value.replace("[淘股吧]", "")
    value = value.replace("[引用原文已无法访问]", "")
    return re.sub(r"\s+", " ", value.replace("\xa0", " ")).strip()


def contains_face_marker(text: str) -> bool:
    return bool(re.search(r"[［\[]表情:\d+[］\]]", text or ""))


def display_matches_full_text(display_text: str, full_text: str, image_urls=()) -> bool:
    display = normalize_author_text(display_text)
    full = normalize_author_text(full_text)
    if not display:
        # The display cap can be consumed entirely by the replied-to quote.
        # In that case text identity is established by reply ID + article +
        # timestamp + username + immutable detail user ID, while the resolved
        # target content must still be non-empty.
        return bool(full or image_urls or contains_face_marker(full_text))
    if full.startswith(display):
        return True
    # One historical display variant drops the amount unit rendered between
    # a decimal and the following CJK stock name (e.g. ``18.8万 通产丽星`` ->
    # ``18.8通产丽星``).  Identity is already bound by reply ID/article/time/
    # immutable user ID; accept only this narrow one-token presentation loss.
    full_without_amount_unit = re.sub(
        r"(?<=\d)[万亿元](?=[\u4e00-\u9fff])", "", full
    )
    return full_without_amount_unit.startswith(display)


def select_unique_target_reply(
    comments: list[CommentRecord], *, reply_id: str, expected_user_id: str
) -> CommentRecord:
    matches = [row for row in comments if row.reply_id == str(reply_id)]
    if not matches:
        raise UserReplyStructureError(f"reply_detail_target_count:{reply_id}:0")
    if any(row.user_id != str(expected_user_id) for row in matches):
        observed = sorted({row.user_id for row in matches})
        raise UserReplyStructureError(
            f"reply_detail_user_id_mismatch:{reply_id}:{observed}"
        )
    unique = {
        (
            row.user_id,
            row.username,
            row.created_at,
            row.text,
            tuple(row.image_urls),
        ): row
        for row in matches
    }
    if len(unique) != 1:
        raise UserReplyStructureError(
            f"reply_detail_conflicting_duplicates:{reply_id}:{len(matches)}"
        )
    return next(iter(unique.values()))


def _clean_feed_text(raw: str) -> tuple[str, int | None]:
    lines = []
    for line in (raw or "").replace("\xa0", " ").splitlines():
        cleaned = re.sub(r"[ \t]+", " ", line).strip()
        if cleaned:
            lines.append(cleaned)
    value = "\n".join(lines).strip()
    match = re.search(r"\s*\((\d+)\)\s*$", value)
    displayed_count = int(match.group(1)) if match else None
    if match:
        value = value[: match.start()].rstrip()
    return strip_third_party_quote(value), displayed_count


def _optional_int(text: str) -> int | None:
    cleaned = re.sub(r"[^0-9-]", "", text or "")
    return int(cleaned) if cleaned and cleaned != "-" else None


def parse_user_reply_feed(
    html: str, *, user_id: str, source_page: int
) -> list[UserReplyFeedRecord]:
    soup = BeautifulSoup(html or "", "html.parser")
    records: list[UserReplyFeedRecord] = []
    for position, node in enumerate(soup.select(".blogReply"), start=1):
        username_node = node.select_one(".blogReply-userName")
        date_node = node.select_one(".blogReply-date")
        article_link = node.select_one('.blogReply-from a[href*="/a/"]')
        reply_link = node.select_one('a.blogReply-subinfo[href*="/a/"]')
        if not all((username_node, date_node, article_link, reply_link)):
            raise UserReplyStructureError(
                f"reply_feed_required_node_missing:{source_page}:{position}"
            )
        article_url = urljoin(BASE_URL, article_link.get("href", ""))
        reply_url = urljoin(BASE_URL, reply_link.get("href", ""))
        article_match = re.fullmatch(
            r"/a/([^/]+)", urlparse(article_url).path.rstrip("/")
        )
        reply_parsed = urlparse(reply_url)
        reply_match = re.fullmatch(
            r"/a/([^/]+)/(\d+)", reply_parsed.path.rstrip("/")
        )
        if not article_match or not reply_match:
            raise UserReplyStructureError(
                f"reply_feed_link_shape_changed:{source_page}:{position}"
            )
        article_slug = article_match.group(1)
        reply_slug, reply_id = reply_match.groups()
        if reply_slug != article_slug:
            raise UserReplyStructureError(
                f"reply_feed_article_slug_mismatch:{source_page}:{position}"
            )
        if reply_parsed.fragment and reply_parsed.fragment != reply_id:
            raise UserReplyStructureError(
                f"reply_feed_fragment_mismatch:{source_page}:{position}"
            )
        author_text, displayed_count = _clean_feed_text(
            reply_link.get_text("\n", strip=False)
        )
        like_node = node.select_one(".zanNums")
        avatar_node = node.select_one("img.blogReply-portrait[src]")
        records.append(
            UserReplyFeedRecord(
                user_id=str(user_id),
                username=username_node.get_text(" ", strip=True),
                reply_id=reply_id,
                reply_created_at=date_node.get_text(" ", strip=True),
                article_slug=article_slug,
                article_title=(
                    article_link.get("title")
                    or article_link.get_text(" ", strip=True)
                ).strip(),
                article_url=article_url,
                reply_url=reply_url,
                author_display_text=author_text,
                displayed_char_count=displayed_count,
                like_count=(
                    _optional_int(like_node.get_text(" ", strip=True))
                    if like_node
                    else None
                ),
                avatar_url=(avatar_node.get("src", "").strip() if avatar_node else ""),
                source_page=source_page,
                position=position,
            )
        )
    return records


def parse_feed_total_pages(
    html: str, *, final_url: str, expected_user_id: str
) -> int:
    parsed = urlparse(final_url)
    current = int((parse_qs(parsed.query).get("pageNo") or ["1"])[0])
    soup = BeautifulSoup(html or "", "html.parser")
    candidates = [current]
    for link in soup.find_all("a", href=True):
        match = re.fullmatch(r"javascript:gotoPage\((\d+)\)", link["href"].strip())
        if match:
            candidates.append(int(match.group(1)))
    hidden = soup.select_one('input[name="userID"]')
    if hidden and str(hidden.get("value", "")).strip() not in {
        "",
        str(expected_user_id),
    }:
        raise UserReplyStructureError("reply_feed_user_id_mismatch")
    return max(candidates)


def validate_feed_page(
    *,
    final_url: str,
    html: str,
    records: list[UserReplyFeedRecord],
    expected_user_id: str,
    expected_username: str,
    expected_page_no: int,
) -> None:
    parsed = urlparse(final_url)
    if parsed.path.rstrip("/") in LOGIN_PATHS or any(
        marker in (html or "") or marker in final_url for marker in LOGIN_MARKERS
    ):
        raise UserReplyAuthenticationError("reply_feed_requires_authenticated_cookie")
    if parsed.path.rstrip("/") != "/user/blog/moreReplyMod":
        raise UserReplyStructureError(
            f"reply_feed_unexpected_final_path:{parsed.path}"
        )
    actual_page = int((parse_qs(parsed.query).get("pageNo") or ["1"])[0])
    if actual_page != expected_page_no:
        raise UserReplyStructureError(
            f"reply_feed_page_redirected:{expected_page_no}->{actual_page}"
        )
    if not records:
        raise UserReplyStructureError(f"reply_feed_page_empty:{expected_page_no}")
    reply_ids = [row.reply_id for row in records]
    if len(reply_ids) != len(set(reply_ids)):
        raise UserReplyStructureError(
            f"reply_feed_duplicate_id_within_page:{expected_page_no}"
        )
    if any(row.user_id != str(expected_user_id) for row in records):
        raise UserReplyStructureError(
            f"reply_feed_record_user_id_mismatch:{expected_page_no}"
        )
    if expected_username and any(
        row.username != expected_username for row in records
    ):
        raise UserReplyStructureError(
            f"reply_feed_username_mismatch:{expected_page_no}"
        )
