import sqlite3
import tempfile
from pathlib import Path
import unittest

from scripts.tgb_author_images import (
    ImageInventoryError,
    _read_image_urls,
    build_image_candidate_urls,
    download_pending_images,
    load_content_image_links,
)


class TestAuthorImages(unittest.TestCase):
    def test_pending_only_does_not_retry_a_known_historical_failure(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            "create table image_sources (source_url text primary key, status text)"
        )
        conn.execute(
            "insert into image_sources values ('https://image.tgb.cn/missing.png', 'error')"
        )
        result = download_pending_images(
            conn,
            session=object(),
            timeout=1,
            max_bytes=1024,
            interval=0,
            retry_failures=False,
        )
        self.assertEqual(result["planned_this_run"], 0)
        self.assertEqual(result["source_urls_attempted_this_run"], 0)
        conn.close()

    @staticmethod
    def build_reply_feed_db(path: Path, rows: list[tuple[str, str, str, str, int]]) -> None:
        conn = sqlite3.connect(path)
        conn.execute(
            """
            create table user_reply_feed_full_texts (
                user_id text not null, reply_id text not null,
                article_slug text not null, image_urls_json text not null,
                display_prefix_verified integer not null
            )
            """
        )
        conn.executemany(
            "insert into user_reply_feed_full_texts values (?, ?, ?, ?, ?)", rows
        )
        conn.commit()
        conn.close()

    def test_generic_inventory_uses_requested_user_id_and_excludes_others(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "tgb-user-777.sqlite"
            conn = sqlite3.connect(db_path)
            conn.executescript(
                """
                create table articles (
                    slug text primary key,
                    source_page integer not null,
                    author_id text not null,
                    image_urls_json text not null
                );
                create table comments (
                    article_slug text not null,
                    page_no integer not null,
                    reply_id text not null,
                    user_id text not null,
                    image_urls_json text not null
                );
                """
            )
            conn.execute(
                "insert into articles values ('post', 1, '777', ?)",
                ('["https://image.tgb.cn/main.png"]',),
            )
            conn.execute(
                "insert into articles values ('other-post', 2, '888', ?)",
                ('["https://image.tgb.cn/other-main.png"]',),
            )
            conn.execute(
                "insert into comments values ('post', 1, 'mine', '777', ?)",
                ('["https://image.tgb.cn/mine.png"]',),
            )
            conn.execute(
                "insert into comments values ('post', 1, 'other', '888', ?)",
                ('["https://image.tgb.cn/other.png"]',),
            )
            conn.execute(
                "insert into comments values ('other-post', 1, 'mine-elsewhere', '777', ?)",
                ('["https://image.tgb.cn/mine-elsewhere.png"]',),
            )
            conn.commit()
            conn.close()

            links = load_content_image_links(db_path, author_id="777")

            self.assertEqual(
                [(row.content_kind, row.reply_id) for row in links],
                [("main_post", ""), ("author_reply", "mine")],
            )
            self.assertTrue(all("other.png" not in row.source_url for row in links))

    def test_historical_first_party_image_hosts_are_allowed_but_others_are_not(self):
        urls = [
            "http://www.taoguba.net/img/2011/08/10/old.JPG",
            "http://www.taoguba.com.cn/img/2014/01/09/old.jpg",
            "http://img.taoguba.com.cn/img/2012/10/18/old.jpg",
            "https://image.tgb.cn/new.png",
        ]
        self.assertEqual(
            _read_image_urls(__import__("json").dumps(urls), identity="legacy"),
            urls,
        )
        with self.assertRaisesRegex(ImageInventoryError, "image_url_not_allowed"):
            _read_image_urls(
                '["https://third-party.example/image.png"]', identity="external"
            )

    def test_historical_image_urls_have_bounded_first_party_fallbacks(self):
        legacy = "http://www.taoguba.net/img/2011/08/10/OLD.JPG"
        self.assertEqual(
            build_image_candidate_urls(legacy),
            [
                legacy,
                "https://image.tgb.cn/img/2011/08/10/OLD.JPG_760w.png",
            ],
        )
        resized = "https://image.tgb.cn/img/2015/02/08/OLD.jpg_760w.png"
        self.assertEqual(
            build_image_candidate_urls(resized),
            [
                resized,
                "https://image.tgb.cn/img/2015/02/08/OLD.jpg_max.png",
                "https://image.tgb.cn/img/2015/02/08/OLD.jpg",
            ],
        )

    def test_reply_feed_adds_external_replies_and_deduplicates_own_topic(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            canonical = Path(tmpdir) / "canonical.sqlite"
            conn = sqlite3.connect(canonical)
            conn.executescript(
                """
                create table articles (
                    slug text primary key, source_page integer not null,
                    author_id text not null, image_urls_json text not null
                );
                create table comments (
                    article_slug text not null, page_no integer not null,
                    reply_id text not null, user_id text not null,
                    image_urls_json text not null
                );
                """
            )
            conn.execute("insert into articles values ('own', 1, '777', '[]')")
            conn.execute(
                "insert into comments values ('own', 1, 'r1', '777', ?)",
                ('["https://image.tgb.cn/own-reply.png"]',),
            )
            conn.commit()
            conn.close()
            reply_feed = Path(tmpdir) / "reply-feed.sqlite"
            self.build_reply_feed_db(
                reply_feed,
                [
                    (
                        "777",
                        "r1",
                        "own",
                        '["https://image.tgb.cn/own-reply.png"]',
                        1,
                    ),
                    (
                        "777",
                        "r2",
                        "external",
                        '["https://image.tgb.cn/external-reply.png"]',
                        1,
                    ),
                    (
                        "888",
                        "r3",
                        "external",
                        '["https://image.tgb.cn/other-author.png"]',
                        1,
                    ),
                    (
                        "777",
                        "r4",
                        "unverified",
                        '["https://image.tgb.cn/unverified.png"]',
                        0,
                    ),
                ],
            )

            links = load_content_image_links(
                canonical, author_id="777", reply_feed_db=reply_feed
            )

            self.assertEqual(
                [(row.article_slug, row.reply_id, row.source_url) for row in links],
                [
                    ("own", "r1", "https://image.tgb.cn/own-reply.png"),
                    ("external", "r2", "https://image.tgb.cn/external-reply.png"),
                ],
            )

    def test_conflicting_duplicate_reply_image_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            canonical = Path(tmpdir) / "canonical.sqlite"
            conn = sqlite3.connect(canonical)
            conn.executescript(
                """
                create table articles (
                    slug text primary key, source_page integer not null,
                    author_id text not null, image_urls_json text not null
                );
                create table comments (
                    article_slug text not null, page_no integer not null,
                    reply_id text not null, user_id text not null,
                    image_urls_json text not null
                );
                """
            )
            conn.execute("insert into articles values ('own', 1, '777', '[]')")
            conn.execute(
                "insert into comments values ('own', 1, 'r1', '777', ?)",
                ('["https://image.tgb.cn/from-canonical.png"]',),
            )
            conn.commit()
            conn.close()
            reply_feed = Path(tmpdir) / "reply-feed.sqlite"
            self.build_reply_feed_db(
                reply_feed,
                [
                    (
                        "777",
                        "r1",
                        "own",
                        '["https://image.tgb.cn/from-feed.png"]',
                        1,
                    )
                ],
            )

            with self.assertRaisesRegex(
                ImageInventoryError, "conflicting_image_link_identity"
            ):
                load_content_image_links(
                    canonical, author_id="777", reply_feed_db=reply_feed
                )


if __name__ == "__main__":
    unittest.main()
