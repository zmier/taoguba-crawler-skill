from __future__ import annotations

import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from common.tgb_comment import CommentRecord, parse_comments, recover_comment_text
from common.tgb_user_replies import (
    UserReplyStructureError,
    UserReplyFeedRecord,
    clean_author_full_text,
    contains_face_marker,
    display_matches_full_text,
    parse_user_reply_feed,
    select_unique_target_reply,
    strip_third_party_quote,
)
from scripts.tgb_author_images import load_reply_feed_image_links
from scripts.tgb_user_replies import (
    advance_known_reply_streak,
    connect_db,
    hydrate_missing,
    merge_incremental_feed,
    resolve_complete_feed_displays,
    store_page,
    status,
    upsert_full_text,
)


class UserReplyCompatibilityTest(unittest.TestCase):
    @staticmethod
    def reply_record(reply_id: str, text: str, position: int) -> UserReplyFeedRecord:
        return UserReplyFeedRecord(
            user_id="2981457",
            username="两个小馒头",
            reply_id=reply_id,
            reply_created_at=f"2026-08-28 15:{position:02d}",
            article_slug="one-billion",
            article_title="1亿实盘",
            article_url="https://www.tgb.cn/a/one-billion",
            reply_url=f"https://www.tgb.cn/a/one-billion/{reply_id}",
            author_display_text=text,
            displayed_char_count=len(text),
            like_count=0,
            avatar_url="avatar",
            source_page=1,
            position=position,
        )

    def test_incremental_boundary_uses_consecutive_baseline_reply_ids(self):
        records = [
            self.reply_record("100", "新增一", 1),
            self.reply_record("101", "新增二", 2),
            self.reply_record("200", "旧一", 3),
            self.reply_record("201", "旧二", 4),
            self.reply_record("202", "旧三", 5),
        ]
        streak, new_ids = advance_known_reply_streak(
            records,
            baseline_reply_ids={"200", "201", "202"},
        )
        self.assertEqual(streak, 3)
        self.assertEqual(new_ids, {"100", "101"})

    def test_incremental_merge_adds_new_reply_and_rehydrates_changed_display(self):
        with TemporaryDirectory() as temp_dir:
            conn = connect_db(Path(temp_dir) / "reply.sqlite")
            try:
                old = self.reply_record("200", "旧文本", 1)
                store_page(
                    conn,
                    user_id="2981457",
                    anchor_date="2026-08-27",
                    page_no=1,
                    page_url="https://example.invalid/page1",
                    final_url="https://example.invalid/page1",
                    html="old-page",
                    records=[old],
                    total_pages=1,
                )
                merge_incremental_feed(
                    conn,
                    user_id="2981457",
                    anchor_date="2026-08-27",
                    scanned_pages=1,
                )
                with conn:
                    upsert_full_text(
                        conn,
                        user_id="2981457",
                        reply_id="200",
                        article_slug="one-billion",
                        text="旧文本",
                        html="",
                        image_urls=[],
                        text_source="complete-reply-feed-display",
                        source_url=old.reply_url,
                    )

                changed = self.reply_record("200", "编辑后的文本", 1)
                new = self.reply_record("300", "今天新增", 2)
                store_page(
                    conn,
                    user_id="2981457",
                    anchor_date="2026-08-28",
                    page_no=1,
                    page_url="https://example.invalid/page1",
                    final_url="https://example.invalid/page1",
                    html="new-page",
                    records=[new, changed],
                    total_pages=2,
                )
                stats = merge_incremental_feed(
                    conn,
                    user_id="2981457",
                    anchor_date="2026-08-28",
                    scanned_pages=1,
                )

                self.assertEqual(stats["new_reply_ids"], ["300"])
                self.assertEqual(stats["updated_reply_ids"], ["200"])
                self.assertEqual(stats["current_records"], 2)
                self.assertEqual(
                    conn.execute(
                        "select count(*) from user_reply_feed_full_texts"
                    ).fetchone()[0],
                    0,
                )
                self.assertEqual(
                    conn.execute(
                        "select count(*) from user_reply_feed_item_revisions"
                    ).fetchone()[0],
                    1,
                )
            finally:
                conn.close()

    def test_feed_parser_keeps_only_target_author_segment(self):
        html = """
        <div class="blogReply">
          <span class="blogReply-userName">author-name</span>
          <span class="blogReply-date">2016-03-18 12:21</span>
          <div class="blogReply-from"><a href="/a/topic-slug" title="topic">topic</a></div>
          <a class="blogReply-subinfo" href="/a/topic-slug/123#123">
            作者自己的回复。[quote]原帖由别人发表：第三方正文[/quote] (120)
          </a>
          <span class="zanNums">3</span>
        </div>
        """
        records = parse_user_reply_feed(html, user_id="206476", source_page=1)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].author_display_text, "作者自己的回复。")
        self.assertNotIn("第三方正文", records[0].author_display_text)
        self.assertEqual(records[0].displayed_char_count, 120)

    def test_quote_truncation_mentions_and_market_prefix_are_compatible(self):
        display = "请 股天乐 看sh600570。[quo"
        detail = "请 @股天乐 看600570。 [引用原文已无法访问]"
        self.assertTrue(display_matches_full_text(display, detail))
        self.assertEqual(strip_third_party_quote("作者[q"), "作者")
        self.assertEqual(clean_author_full_text(detail), "请 @股天乐 看600570。")
        self.assertEqual(
            clean_author_full_text("作者自己的回答。[quote]第三方问题"),
            "作者自己的回答。",
        )
        self.assertTrue(
            display_matches_full_text("持股1天（ gt;90%)", "持股1天（ 90%) 后续")
        )
        self.assertTrue(
            display_matches_full_text("模式内应该操作 &", "模式内应该操作 那一块。")
        )
        self.assertTrue(
            display_matches_full_text(
                "一起加油\n我也亏的不要不要的",
                "一起加油 ［表情:009］ 我也亏的不要不要的",
            )
        )
        self.assertTrue(
            display_matches_full_text(
                "[查看战绩]吐槽几句:。。。。。。",
                "查看战绩 吐槽几句:。。。。。。",
            )
        )
        self.assertTrue(
            display_matches_full_text(
                "希望不要有第三次。。。［图",
                "希望不要有第三次。。。 ［表情:017］",
                ["https://image.tgb.cn/a.png"],
            )
        )
        self.assertTrue(
            display_matches_full_text(
                "@米兰 这两天未上淘股吧 nbs",
                "@米兰 这两天未上淘股吧 才看到信息",
            )
        )
        self.assertTrue(
            display_matches_full_text(
                "今日收盘资产：18.8通产丽星板砸",
                "今日收盘资产：18.8万 通产丽星 板砸低吸",
            )
        )
        self.assertTrue(
            display_matches_full_text(
                "天富能源看下午",
                "天富[gubar]能源[/gubar]看下午",
            )
        )

    def test_face_only_detail_can_resolve_empty_or_image_like_feed_display(self):
        self.assertTrue(contains_face_marker("［表情:001］"))
        self.assertTrue(display_matches_full_text("", "［表情:001］"))

    def test_face_only_comment_is_preserved_as_a_source_marker(self):
        html = """
        <div class="comment-data" id="reply_206476_123" ustr="206476">
          <div class="comment-data-user"><a class="user-name">author</a></div>
          <div class="comment-data-text" id="reply123">
            <img src="https://css.tgb.cn/images/face/033.png"/>
          </div>
        </div>
        """
        parsed = parse_comments(html, article_slug="topic", page_no=1)
        self.assertEqual(parsed[0].text, "［表情:033］")
        self.assertEqual(parsed[0].image_urls, [])
        self.assertEqual(
            recover_comment_text(
                "", '<div><img src="https://css.tgb.cn/images/face/007.png"/></div>'
            ),
            "［表情:007］",
        )

    def test_quote_before_author_reply_keeps_author_suffix(self):
        raw = "[quote]第三方问题[/quote]这是作者自己的回答"
        self.assertEqual(strip_third_party_quote(raw), "这是作者自己的回答")

    def test_quote_consumes_entire_preview_but_detail_can_resolve_identity(self):
        self.assertEqual(strip_third_party_quote("[quote]第三方问题"), "")
        self.assertTrue(display_matches_full_text("", "作者详情正文"))

    def test_identical_dom_duplicate_is_accepted_but_conflict_fails(self):
        def row(text: str) -> CommentRecord:
            return CommentRecord(
                article_slug="topic-slug",
                page_no=0,
                reply_id="123",
                user_id="206476",
                username="author-name",
                is_author=False,
                floor_label="",
                created_at="2016-03-18 12:21",
                text=text,
                html=f"<p>{text}</p>",
                image_urls=[],
            )

        selected = select_unique_target_reply(
            [row("same"), row("same")], reply_id="123", expected_user_id="206476"
        )
        self.assertEqual(selected.text, "same")
        with self.assertRaisesRegex(UserReplyStructureError, "conflicting_duplicates"):
            select_unique_target_reply(
                [row("a"), row("b")], reply_id="123", expected_user_id="206476"
            )

    def test_only_untruncated_feed_display_can_be_terminal_full_text(self):
        with TemporaryDirectory() as temp_dir:
            conn = connect_db(Path(temp_dir) / "reply.sqlite")
            try:
                for reply_id, text, count in [
                    ("1", "完整作者段", 5),
                    ("2", "被截断作者段", 140),
                    ("3", "字" * 100, 100),
                ]:
                    conn.execute(
                        """
                        insert into user_reply_feed_items (
                          user_id,username,reply_id,reply_created_at,article_slug,
                          article_title,article_url,reply_url,reply_text,
                          displayed_char_count,like_count,avatar_url,source_page,
                          position,anchor_date,row_html,captured_at
                        ) values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            "206476", "author-name", reply_id,
                            "2014-12-15 15:41", "topic", "title",
                            "https://www.tgb.cn/a/topic",
                            f"https://www.tgb.cn/a/topic/{reply_id}",
                            text, count, None, "", 1, int(reply_id),
                            "2026-08-26", "", "now",
                        ),
                    )
                conn.commit()
                self.assertEqual(resolve_complete_feed_displays(conn, "206476"), 1)
                stored = conn.execute(
                    "select reply_id from user_reply_feed_full_texts"
                ).fetchall()
                self.assertEqual([row[0] for row in stored], ["1"])
            finally:
                conn.close()

    def test_full_hydration_recovers_unmarked_images_from_new_and_legacy_capped_displays(self):
        display = "字" * 100
        author = "2981457"
        legacy = self.reply_record("101", display, 1)
        new = self.reply_record("102", display, 2)
        with TemporaryDirectory() as temp_dir:
            db = Path(temp_dir) / "reply.sqlite"
            with closing(connect_db(db)) as conn:
                # The incremental scan only visits the new reply. The old preview
                # is still in the archive with the pre-fix completeness flag.
                for day, record in [("2026-08-27", legacy), ("2026-08-28", new)]:
                    store_page(conn, user_id=author, anchor_date=day, page_no=1,
                               page_url="page1", final_url="page1", html="", records=[record], total_pages=1)
                    merge_incremental_feed(conn, user_id=author, anchor_date=day, scanned_pages=1)
                with conn:
                    upsert_full_text(conn, user_id=author, reply_id=legacy.reply_id,
                                     article_slug=legacy.article_slug, text=display, html="", image_urls=[],
                                     text_source="complete-reply-feed-display", source_url=legacy.reply_url)
                self.assertEqual(resolve_complete_feed_displays(conn, author), 0)
                before = status(conn, author)
                self.assertEqual(before["full_text_records"], 0)
                self.assertEqual(before["unresolved"], 2)
                self.assertEqual(before["unverified_capped_displays"], 1)
                self.assertFalse(before["full_hydration_complete"])

                def detail_page(session, url, timeout):
                    reply_id = url.rsplit("/", 1)[-1]
                    source = legacy if reply_id == legacy.reply_id else new
                    return (f'<div class="comment-data" ustr="{author}">'
                            f'<div class="comment-data-user"><a class="user-name">{source.username}</a></div>'
                            f'<span class="pcyclspan">{source.reply_created_at}</span>'
                            f'<div class="comment-data-text" id="reply{reply_id}">'
                            f'{display}完整尾句<img data-original="https://image.tgb.cn/{reply_id}.png">'
                            f'</div></div>', url)

                with patch("scripts.tgb_user_replies.request_html", side_effect=detail_page) as fetch:
                    for expected_fetches in (2, 0):
                        run = hydrate_missing(conn, session=Mock(), user_id=author, interval=0, timeout=1, limit=0)
                        self.assertEqual(run["hydrate_planned"], expected_fetches)
                        self.assertEqual(run["hydrate_succeeded"], expected_fetches)
                    self.assertEqual(fetch.call_count, 2)
                self.assertTrue(status(conn, author)["full_hydration_complete"])
                texts = conn.execute("select full_text, text_source from user_reply_feed_full_texts").fetchall()
                self.assertEqual([tuple(row) for row in texts], [(display + "完整尾句", "direct-reply-page-v3")] * 2)
                media = load_reply_feed_image_links(db, author_id=author)
                self.assertEqual([(item.reply_id, item.source_url) for item in media],
                                 [("101", "https://image.tgb.cn/101.png"), ("102", "https://image.tgb.cn/102.png")])

    def test_image_marker_is_not_full_hydration_without_detail_image_urls(self):
        with TemporaryDirectory() as temp_dir:
            conn = connect_db(Path(temp_dir) / "reply.sqlite")
            try:
                conn.execute(
                    """
                    insert into user_reply_feed_items (
                      user_id,username,reply_id,reply_created_at,article_slug,
                      article_title,article_url,reply_url,reply_text,
                      displayed_char_count,like_count,avatar_url,source_page,
                      position,anchor_date,row_html,captured_at
                    ) values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        "206476", "author-name", "1", "2014-12-15 15:41",
                        "topic", "title", "https://www.tgb.cn/a/topic",
                        "https://www.tgb.cn/a/topic/1", "［图片］", 4,
                        None, "", 1, 1, "2026-08-26", "", "now",
                    ),
                )
                conn.commit()
                self.assertEqual(resolve_complete_feed_displays(conn, "206476"), 1)
                current = status(conn, "206476")
                self.assertTrue(current["full_text_complete"])
                self.assertEqual(current["image_unresolved_records"], 1)
                self.assertFalse(current["full_hydration_complete"])
            finally:
                conn.close()

    def test_face_only_detail_closes_image_like_feed_marker(self):
        with TemporaryDirectory() as temp_dir:
            conn = connect_db(Path(temp_dir) / "reply.sqlite")
            try:
                conn.execute(
                    """
                    insert into user_reply_feed_items (
                      user_id,username,reply_id,reply_created_at,article_slug,
                      article_title,article_url,reply_url,reply_text,
                      displayed_char_count,like_count,avatar_url,source_page,
                      position,anchor_date,row_html,captured_at
                    ) values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        "2981457", "两个小馒头", "35196758", "2019-04-17 19:07",
                        "topic", "title", "https://www.tgb.cn/a/topic",
                        "https://www.tgb.cn/a/topic/35196758#35196758",
                        "文字［图片］", 65, 0, "avatar", 1, 1, "2026-08-28", "", "now",
                    ),
                )
                conn.execute(
                    """
                    insert into user_reply_feed_full_texts (
                      user_id,reply_id,article_slug,full_text,full_text_html,
                      image_urls_json,text_source,source_url,source_database_sha256,
                      full_text_sha256,display_prefix_verified,resolved_at
                    ) values (?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        "2981457", "35196758", "topic", "文字 ［表情:001］", "",
                        "[]", "direct-reply-page-v3", "https://www.tgb.cn/a/topic/35196758",
                        "", "digest", 1, "now",
                    ),
                )
                current = status(conn, "2981457")
                self.assertEqual(current["image_face_only_records"], 1)
                self.assertEqual(current["image_unresolved_records"], 0)
                self.assertTrue(current["full_hydration_complete"])
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
