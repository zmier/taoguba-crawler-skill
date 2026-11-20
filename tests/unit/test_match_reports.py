import base64
import csv
import hashlib
import json
from contextlib import closing

import pytest

from common import tgb_match_reports as mr
from scripts import tgb_match_reports as collector


UID = "771"
DAY = "20240108"
PREVIOUS = "20240105"
IMAGE = "https://image.tgb.cn/report.png"


def match_url(seq, uid=UID):
    return f"{mr.ORIGIN}/spmatch/gains/readInfo?spmatchSeq={seq}&lookeUserID={uid}"


def cells(*values):
    return [dict(value=value, action="", hidden=False) for value in values]


def visible_match(seq):
    heading = cells("日期", "今收益", "今资产(存取)", "股票名称", "类别", "数量", "持仓金额", "报单原图")
    first = cells(DAY, "+2%", "51万元", "甲", "持有", "--", "**", "查看")
    first[-1]["action"] = f"selectImageList({seq},{UID},{DAY})"
    second = cells("", "", "甲", "持有", "--", "**", "")
    for index in (0, 1, 6):
        second[index]["hidden"] = True
    income_head = cells(
        "日期",
        "初始资产（万元）",
        "昨日资产（万元）",
        "今资产（万元）",
        "存取（元）",
        "今盈亏（元）",
        "仓位",
        "昨收益",
        "今收益",
        "总收益",
        "排名",
        "持有股票",
        "备注",
    )
    income = cells(DAY[2:], "50", "50", "51", "0", "10000", "70%", "--", "2%", "2%", "3", "1", "")
    return dict(
        seq=seq,
        url=match_url(seq),
        tables={"持仓": [[heading, first, second]], "收益明细": [[income_head, income]]},
    )


def test_directory_requires_an_explicit_empty_state_and_target_identity():
    heading = f'<a href="/blog/{UID}">作者</a><div><div>参加的比赛</div>'
    assert mr.parse_directory(heading + "<div>暂无实盘比赛数据</div></div>", UID) == []
    with pytest.raises(ValueError, match="明确空态"):
        mr.parse_directory(heading + "</div>", UID)
    card = (
        '<div class="container-match-list"><b class="match-top-name">赛事</b><a href="{}">战绩</a></div>'
    )
    assert len(mr.parse_directory(heading + card.format(match_url("90")) + "</div>", UID)) == 1
    with pytest.raises(ValueError, match="参赛者"):
        mr.parse_directory(heading + card.format(match_url("90", "999")) + "</div>", UID)


def test_gallery_requires_both_terminal_pages_and_strictly_advancing_dates():
    buttons = {("90", DAY)}
    previous = dict(day=PREVIOUS, submitted="2024-01-06 20:15", urls=[IMAGE])
    trace = mr.walk(
        DAY, lambda cursor, direction: [previous] if (cursor, direction) == (DAY, "Y") else []
    )
    assert mr.navigation_links({"90": trace}, buttons) == {
        ("90", PREVIOUS): [[previous["submitted"], 1, IMAGE]]
    }
    with pytest.raises(ValueError, match="中断"):
        mr.navigation_links({"90": trace[:-1]}, buttons)
    with pytest.raises(ValueError, match="方向推进"):
        mr.walk(DAY, lambda *_: [previous])
    assert mr.gallery_groups({"status": False, "errorCode": "10120", "errorMessage": "暂无图片"}) == []
    with pytest.raises(ValueError, match="请求失败"):
        mr.gallery_groups({"status": False, "errorCode": "10120", "errorMessage": "登录失效"})
    with pytest.raises(ValueError, match="响应结构变化"):
        mr.gallery_groups({"status": True})


def test_replay_preserves_overlap_and_source_dates_and_rejects_other_owners(tmp_path, monkeypatch):
    def offline(*args, **kwargs):
        pytest.fail("离线回放发起了网络请求")

    monkeypatch.setattr(collector.requests.Session, "request", offline)
    tables = [visible_match(seq) for seq in ("90", "91")]
    tables[0]["tables"]["交割单"] = [[cells("日期"), cells(DAY)]]
    mr.write_json(tmp_path / "账号.json", {"author_id": UID})
    mr.write_json(tmp_path / mr.CARDS, [{"url": m["url"]} for m in tables])
    mr.write_json(tmp_path / mr.TABLES, tables)
    mr.write_json(tmp_path / mr.NAV, {m["seq"]: mr.walk(DAY, lambda *_: []) for m in tables})

    image = b"fixture bytes"
    digest = hashlib.sha256(image).hexdigest()
    submitted = "2024-01-09 22:40"
    with closing(collector.connect_cache(tmp_path / mr.MEDIA)) as db, db:
        db.execute(
            "insert into files values(?,?,?,?)",
            (digest, len(image), "image/png", base64.b64encode(image)),
        )
        db.execute("insert into sources values(?,?)", (IMAGE, digest))
        for m in tables:
            db.execute(
                "insert into galleries values(?,?,?)",
                (m["seq"], DAY, json.dumps([[submitted, 1, IMAGE]])),
            )
    assert collector.run(UID, tmp_path, "replay") == 2
    assert mr.read_json(tmp_path / mr.AUDIT)["unmapped_tabs"] == [["90", "交割单"]]
    del tables[0]["tables"]["交割单"]
    mr.write_json(tmp_path / mr.TABLES, tables)

    assert collector.run(UID, tmp_path, "replay") == 0
    audit = mr.read_json(tmp_path / mr.AUDIT)
    assert (audit["unique_income_dates"], audit["placements"], audit["unique_images"]) == (1, 2, 1)
    with (tmp_path / mr.HOLDINGS).open(encoding="utf-8-sig") as source:
        rows = list(csv.DictReader(source))
    assert [(r["比赛ID"], r["日期"], r["数量"]) for r in rows] == [
        ("90", DAY, "--"),
        ("90", DAY, "--"),
        ("91", DAY, "--"),
        ("91", DAY, "--"),
    ]
    with (tmp_path / mr.PHOTOS).open(encoding="utf-8-sig") as source:
        assert [(r["报单日期"], r["报单时间"]) for r in csv.DictReader(source)] == [(DAY, submitted)] * 2
    with pytest.raises(ValueError, match="其他作者"):
        collector.run("999", tmp_path, "replay")
