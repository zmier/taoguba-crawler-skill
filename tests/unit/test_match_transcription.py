import base64
import hashlib
import json
import sqlite3
from contextlib import closing
from types import SimpleNamespace

import pytest

from common import tgb_match_reports as mr
from scripts.tgb_match_reports import connect_cache
from scripts.tgb_match_transcription import prepare


def test_match_queue_keeps_dates_and_reuses_bytes_without_changing_input(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    uid, digest = "111", hashlib.sha256(b"abc").hexdigest()
    url = "https://image.tgb.cn/img/test.png"
    mr.write_json(
        root / mr.CARDS,
        [
            {"url": mr.ORIGIN + f"/spmatch/gains/readInfo?lookeUserID={uid}&spmatchSeq={seq}"}
            for seq in ("10", "12")
        ],
    )
    raw = [[seq, "20240101", "20240102 10:00", 1, url, digest] for seq in ("10", "12")]
    mr.write_csv(root / mr.PHOTOS, mr.PHOTO_HEADER, raw)
    mr.write_json(root / mr.AUDIT, {"author_id": uid, "placements": 2, "unique_images": 1})
    with closing(connect_cache(root / mr.MEDIA)) as db, db:
        db.execute(
            "insert into files values(?,?,?,?)", (digest, 3, "image/png", base64.b64encode(b"abc"))
        )
        db.execute("insert into sources values(?,?)", (url, digest))
        db.executemany(
            "insert into galleries values(?,?,?)", [(r[0], r[1], json.dumps([r[2:5]])) for r in raw]
        )
    output = tmp_path / "queue.sqlite"
    before = (root / mr.MEDIA).read_bytes()
    for _ in range(2):
        assert prepare(root, uid, output, SimpleNamespace(max_assets=0)) == 0
    assert before == (root / mr.MEDIA).read_bytes()
    with closing(sqlite3.connect(output)) as db:
        assert db.execute("select occurrences,classification from stage_a_review_queue").fetchall() == [
            (2, None)
        ]
        assert db.execute(
            "select distinct report_day,submitted_at from match_placements"
        ).fetchall() == [("20240101", "20240102 10:00")]
    with pytest.raises(ValueError, match="作者"):
        prepare(root, "222", output, SimpleNamespace(max_assets=0))
    with closing(connect_cache(root / mr.MEDIA)) as db, db:
        db.execute("update files set byte_size=2")
    with pytest.raises(ValueError, match="字节"):
        prepare(root, uid, output, SimpleNamespace(max_assets=0))
