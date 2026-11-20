"""Source rules for an athlete's visible competition records."""

import csv
import json
import re
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime
from urllib.parse import parse_qs, urljoin, urlsplit

from bs4 import BeautifulSoup

ORIGIN = "https://www.tgb.cn"
CARDS = "赛事目录.json"
TABLES = "网页表格.json"
NAV = "相册翻页.json"
MEDIA = "比赛报单原图.sqlite"
AUDIT = "覆盖核对.json"
HOLDINGS = "逐日持仓报单.csv"
INCOME = "逐日收益明细.csv"
PHOTOS = "比赛报单原图索引.csv"
HOLD_HEADER = [
    "比赛ID",
    "页码",
    "页内行",
    "日期",
    "今收益",
    "今资产及存取",
    "股票名称",
    "类别",
    "数量",
    "持仓金额",
    "报单原图入口",
]
INCOME_HEADER = [
    "比赛ID",
    "页码",
    "页内行",
    "日期",
    "初始资产(万元)",
    "昨日资产(万元)",
    "今资产(万元)",
    "存取(元)",
    "今盈亏(元)",
    "仓位",
    "昨收益",
    "今收益",
    "总收益",
    "排名",
    "持有股票数",
    "备注",
    "说明",
]
PHOTO_HEADER = ["比赛ID", "报单日期", "报单时间", "图序", "原图链接", "SHA256"]


@contextmanager
def atomic_text(path, encoding="utf-8"):
    temp = path.with_name("." + path.name + ".tmp")
    try:
        with temp.open("w", encoding=encoding, newline="") as handle:
            yield handle
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def write_json(path, data):
    with atomic_text(path) as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_csv(path, header, rows):
    with atomic_text(path, "utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def match_id(url, uid):
    parsed = urlsplit(url)
    params = parse_qs(parsed.query)
    seq = params.get("spmatchSeq", [])
    if (
        (parsed.scheme, parsed.netloc, parsed.path) != ("https", "www.tgb.cn", "/spmatch/gains/readInfo")
        or params.get("lookeUserID") != [uid]
        or len(seq) != 1
        or not re.fullmatch("[0-9]+", seq[0])
    ):
        raise ValueError("比赛链接的域名、参赛者或赛事 ID 不符")
    return seq[0]


def parse_directory(html, uid):
    doc = BeautifulSoup(html, "html.parser")
    blog = f"/blog/{uid}"
    heading = doc.find(string=lambda s: s and s.strip() == "参加的比赛")
    if not heading or not doc.find("a", href=lambda u: u in (blog, ORIGIN + blog)):
        raise ValueError("无法确认目标账号的比赛栏目")
    region = heading.parent.parent
    while (
        region
        and not region.select_one(".container-match-list")
        and not region.find(string=lambda s: s and s.strip() == "暂无实盘比赛数据")
    ):
        region = region.parent
    if not region:
        raise ValueError("赛事目录结构变化或未显示明确空态")
    cards = []
    for card in region.select(".container-match-list"):

        def label(selector):
            node = card.select_one(selector)
            return node.get_text(" ", strip=True) if node else ""

        link = card.select_one('a[href*="gains/readInfo"]')
        if not link or not label(".match-top-name"):
            raise ValueError("赛事卡片缺少标题或战绩链接")
        url = urljoin(ORIGIN, link["href"])
        match_id(url, uid)
        cards.append(
            dict(
                title=re.sub(r"\s+", "", label(".match-top-name")),
                rank=label(".match-top-biaoshi"),
                dates=label(".match-top-time"),
                card_text=" ".join(card.stripped_strings).strip(),
                url=url,
            )
        )
    if len({match_id(c["url"], uid) for c in cards}) != len(cards):
        raise ValueError("赛事目录出现重复赛事")
    return cards


def day_key(value):
    day = str(value)
    if not re.fullmatch("[0-9]{8}", day):
        raise ValueError("报单日期格式不符")
    datetime.strptime(day, "%Y%m%d")
    return day


def verify_url(url):
    if (urlsplit(url).scheme, urlsplit(url).netloc) != ("https", "image.tgb.cn"):
        raise ValueError("报单图片地址不属于平台原图域名")
    return url


def dates_and_tables(uid, cards, tables):
    expected = {match_id(c["url"], uid) for c in cards}
    seen = set()
    holdings, income, buttons, locked = [], [], set(), set()
    for m in tables:
        seq = match_id(m["url"], uid)
        if seq != m["seq"] or seq in seen or seq not in expected:
            raise ValueError("表格与赛事目录不一致")
        seen.add(seq)
        tab = m["tables"]
        if "收益明细" not in tab or not ({"持仓", "交割单"} & tab.keys()):
            raise ValueError("赛事表格缺失")
        for page, table in enumerate(tab.get("持仓", []), 1):
            if [c["value"] for c in table[0]] != [
                "日期",
                "今收益",
                "今资产(存取)",
                "股票名称",
                "类别",
                "数量",
                "持仓金额",
                "报单原图",
            ]:
                raise ValueError("持仓表头变化")
            date = rate = balance = photo = ""
            for num, cells in enumerate(table[1:], 1):
                if len(cells) == 7 and all(cells[i]["hidden"] for i in (0, 1, 6)):
                    cells = [{"value": "", "action": ""}, *cells]
                if len(cells) != 8:
                    raise ValueError("持仓列数变化")
                fields = [c["value"] for c in cells]
                if fields[0]:
                    date = day_key(fields[0])
                    rate, balance, photo = fields[1], fields[2], fields[7]
                if not date:
                    raise ValueError("持仓行缺少报单日期")
                action = cells[-1]["action"]
                if action:
                    args = re.fullmatch(
                        r"selectImageList\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)", action
                    )
                    if not args or args.groups() != (seq, uid, date) or photo != "查看":
                        raise ValueError("相册入口与报单身份不符")
                    buttons.add((seq, date))
                elif fields[7] == "查看":
                    raise ValueError("缺少相册入口")
                if photo == "解锁":
                    locked.add((seq, date))
                holdings.append([seq, page, num, date, rate, balance, *fields[3:7], photo])
        dates = set()
        for page, table in enumerate(tab["收益明细"], 1):
            labels = [re.sub(r"\s+", "", c["value"]) for c in table[0]]
            if (
                len(labels) != 13
                or labels[:4] != ["日期", "初始资产（万元）", "昨日资产（万元）", "今资产（万元）"]
                or labels[4:]
                != [
                    "存取（元）",
                    "今盈亏（元）",
                    "仓位",
                    "昨收益",
                    "今收益",
                    "总收益",
                    "排名",
                    "持有股票",
                    "备注",
                ]
            ):
                raise ValueError("收益明细表头变化")
            for num, cells in enumerate(table[1:], 1):
                fields = [c["value"] for c in cells]
                if len(fields) == 1 and income and income[-1][0] == seq:
                    income[-1][-1] += fields[0]
                    continue
                if len(fields) != 13:
                    raise ValueError("收益列数变化")
                fields[0] = day_key("20" + fields[0] if len(fields[0]) == 6 else fields[0])
                if fields[0] in dates:
                    raise ValueError("同一赛事日收益重复")
                dates.add(fields[0])
                income.append([seq, page, num, *fields, ""])
    if seen != expected:
        raise ValueError("缺少目录所列赛事表格")
    return holdings, income, buttons, locked


def gallery_groups(reply):
    if reply.get("status") is not True:
        if (
            reply.get("status") is False
            and str(reply.get("errorCode")) == "10120"
            and reply.get("errorMessage") == "暂无图片"
            and not reply.get("dto")
        ):
            return []
        raise ValueError("相册请求失败，请检查会话与可见性")
    if "dto" not in reply:
        raise ValueError("相册响应结构变化")
    groups = reply["dto"]
    if groups is None:
        return []
    if not isinstance(groups, list):
        raise ValueError("相册响应结构变化")
    entries = []
    for group in groups:
        urls = group["imgUrls"]
        if not isinstance(urls, list):
            raise ValueError("相册缺少图序")
        entries.append(
            dict(
                day=day_key(group["dateNum"]),
                submitted=group["updateTimeStr"],
                urls=[verify_url(u) for u in urls],
            )
        )
    return entries


def walk(anchor, fetch):
    trace = []
    for direction in ("N", "Y"):
        cursor = anchor
        while True:
            entries = fetch(cursor, direction)
            trace.append(dict(direction=direction, anchor=cursor, entries=entries))
            if not entries:
                break
            days = [e["day"] for e in entries]
            if not all(d > cursor if direction == "N" else d < cursor for d in days):
                raise ValueError("相册游标未按方向推进")
            cursor = max(days) if direction == "N" else min(days)
    return trace


def navigation_links(trace, buttons):
    starts = {}
    for seq, day in sorted(buttons):
        starts[seq] = day
    if set(trace) != set(starts):
        raise ValueError("相册与可见入口的赛事集合不符")
    output = defaultdict(list)
    for seq, start in starts.items():
        pages = iter(trace[seq])

        def replay(cursor, direction):
            page = next(pages, None)
            if not page or (page["anchor"], page["direction"]) != (cursor, direction):
                raise ValueError("相册翻页记录缺失或中断")
            for entry in page["entries"]:
                key = seq, day_key(entry["day"])
                for ordinal, url in enumerate(entry["urls"], 1):
                    item = [entry["submitted"], ordinal, verify_url(url)]
                    if item not in output[key]:
                        output[key].append(item)
            return page["entries"]

        walk(start, replay)
        if next(pages, None) is not None:
            raise ValueError("相册终点之后出现额外分页")
    return output
