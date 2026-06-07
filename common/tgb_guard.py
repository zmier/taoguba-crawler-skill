from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class GuardDecision(str, Enum):
    NORMAL = "normal"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


class AntiBotBlocked(RuntimeError):
    pass


@dataclass(frozen=True)
class ConservativeCrawlPolicy:
    request_interval_seconds: float = 10.0
    max_list_pages_per_batch: int = 1
    max_articles_per_page: int = 5
    max_comment_pages_per_article: int = 1
    cooldown_minutes_on_block: int = 60


def classify_tgb_page(html: str, expected: str = "article") -> GuardDecision:
    text = html or ""
    if _looks_blocked(text):
        return GuardDecision.BLOCKED
    if expected == "bbs_list":
        return GuardDecision.NORMAL if "/bbs/" in text and "gotoPage" in text else GuardDecision.UNKNOWN
    if expected in {"article", "comment_page"}:
        if any(marker in text for marker in ('id="stockTitle"', "id='stockTitle'", "article-tittle")):
            return GuardDecision.NORMAL
        if "comment-data" in text or 'id="first"' in text or "article-text p_coten" in text:
            return GuardDecision.NORMAL
        return GuardDecision.UNKNOWN
    return GuardDecision.UNKNOWN


def require_normal_page(html: str, url: str, expected: str) -> None:
    decision = classify_tgb_page(html, expected=expected)
    if decision == GuardDecision.BLOCKED:
        raise AntiBotBlocked(f"blocked page detected: {url}")
    if decision == GuardDecision.UNKNOWN and expected in {"article", "comment_page"}:
        raise AntiBotBlocked(f"unexpected page structure, possible block: {url}")


def _looks_blocked(html: str) -> bool:
    markers = [
        "错误页面_淘股吧",
        "访问太频繁",
        "请稍后再试",
        "<title>安全验证",
        "请输入验证码",
    ]
    return any(marker in html for marker in markers)
