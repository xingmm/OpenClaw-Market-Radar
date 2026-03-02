#!/usr/bin/env python3
"""Fetch Eastmoney fast news and generate portfolio/macro focused brief."""

from __future__ import annotations

import argparse
import json
import re
import uuid
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List

import requests

API_URL = os.getenv(
    "OCMR_FASTNEWS_API_URL",
    "https://np-weblist.eastmoney.com/comm/web/getFastNewsList",
)
DEFAULT_COLUMNS = "102,103,104,105"

MACRO_KEYWORDS = [
    "央行",
    "证监会",
    "财政",
    "社融",
    "CPI",
    "PPI",
    "人民币",
    "汇率",
    "降息",
    "加息",
    "关税",
    "地缘",
    "战争",
    "冲突",
    "停火",
    "制裁",
    "中东",
    "俄乌",
    "俄罗斯",
    "乌克兰",
    "以色列",
    "伊朗",
    "原油",
    "黄金",
    "美股",
    "纳指",
    "标普",
    "恒指",
    "港股",
    "A股",
    "沪指",
    "深成指",
    "创业板",
]

IMPORTANCE_KEYWORDS = [
    "暴涨",
    "暴跌",
    "大幅",
    "超预期",
    "不及预期",
    "新规",
    "发布",
    "处罚",
    "重组",
    "IPO",
    "回购",
    "增持",
    "减持",
    "财报",
]

AI_KEYWORDS = [
    "人工智能",
    "AI",
    "大模型",
    "模型",
    "机器人",
    "人形机器人",
    "GPU",
    "算力",
    "芯片",
    "半导体",
    "英伟达",
    "NVIDIA",
    "CPO",
    "服务器",
    "数据中心",
]

SECTOR_KEYWORDS = [
    "新能源",
    "光伏",
    "储能",
    "锂电",
    "锂电池",
    "电池",
    "汽车",
    "智能汽车",
    "新能源车",
    "比亚迪",
    "宁德时代",
    "隆基",
    "通威",
    "逆变器",
    "充电桩",
]


@dataclass
class NewsItem:
    show_time: str
    title: str
    summary: str
    score: int
    priority: str
    freshness_score: int
    tags: List[str]


def load_holdings(holding_md: Path) -> List[str]:
    text = holding_md.read_text(encoding="utf-8")
    holdings = []
    in_holding_section = False

    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("## 持仓清单"):
            in_holding_section = True
            continue
        if in_holding_section and line.startswith("## 建议分组"):
            break
        if not in_holding_section:
            continue

        if not line.startswith("- "):
            continue
        name = line[2:].strip()
        if not name:
            continue
        # Keep simple stock/ETF names only.
        if len(name) <= 16 and not any(ch in name for ch in ["：", "，", "("]):
            holdings.append(name)
    # deduplicate while preserving order
    seen = set()
    result = []
    for h in holdings:
        if h in seen:
            continue
        seen.add(h)
        result.append(h)
    return result


def fetch_fastnews(page_size: int) -> list[dict]:
    params = {
        "client": "web",
        "biz": "web_724",
        "fastColumn": DEFAULT_COLUMNS,
        "sortEnd": "",
        "pageSize": str(page_size),
        "req_trace": str(uuid.uuid4()),
    }
    resp = requests.get(API_URL, params=params, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    data = resp.json()
    if str(data.get("code")) != "1":
        raise RuntimeError(f"API returned non-success code: {data.get('code')}")
    return data.get("data", {}).get("fastNewsList", [])


def parse_show_time(show_time: str) -> datetime | None:
    if not show_time:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(show_time, fmt)
        except ValueError:
            continue
    return None


def freshness_and_priority(show_time: str, now: datetime) -> tuple[int, str]:
    ts = parse_show_time(show_time)
    if ts is None:
        return 0, "P3"
    age_hours = max(0.0, (now - ts).total_seconds() / 3600.0)
    if age_hours <= 3:
        return 3, "P1"
    if age_hours <= 12:
        return 2, "P2"
    if age_hours <= 24:
        return 1, "P2"
    return 0, "P3"


def normalize_title(title: str) -> str:
    return re.sub(r"\s+", "", title).strip().lower()


def deduplicate_by_title(items: List[NewsItem]) -> List[NewsItem]:
    seen = set()
    deduped: List[NewsItem] = []
    for item in items:
        key = normalize_title(item.title)
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def score_item(item: dict, holdings: List[str], now: datetime) -> NewsItem:
    title = item.get("title", "")
    summary = item.get("summary", "")
    text = f"{title} {summary}"

    tags: List[str] = []
    score = 0

    related_holdings = [h for h in holdings if h in text]
    if related_holdings:
        tags.append("持仓相关:" + "、".join(related_holdings))
        score += 4 + len(related_holdings)

    macro_hits = [k for k in MACRO_KEYWORDS if k in text]
    if macro_hits:
        tags.append("宏观/市场:" + "、".join(macro_hits[:4]))
        score += 2

    imp_hits = [k for k in IMPORTANCE_KEYWORDS if k in text]
    if imp_hits:
        tags.append("重要事件:" + "、".join(imp_hits[:3]))
        score += 1

    ai_hits = [k for k in AI_KEYWORDS if k in text]
    if ai_hits:
        tags.append("AI/科技:" + "、".join(ai_hits[:4]))
        score += 2

    sector_hits = [k for k in SECTOR_KEYWORDS if k in text]
    if sector_hits:
        tags.append("产业赛道:" + "、".join(sector_hits[:4]))
        score += 2

    # Penalize irrelevant geopolitical headline if no macro/holding/AI/sector relation.
    if "以色列" in text and not related_holdings and not macro_hits and not ai_hits and not sector_hits:
        score -= 1

    freshness_score, priority = freshness_and_priority(item.get("showTime", ""), now)
    score += freshness_score
    tags.append(f"优先级:{priority}")

    return NewsItem(
        show_time=item.get("showTime", ""),
        title=title,
        summary=summary,
        score=score,
        priority=priority,
        freshness_score=freshness_score,
        tags=tags,
    )


def build_markdown(items: List[NewsItem], holdings: List[str]) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        f"# 快讯雷达（持仓 + 宏观）\n",
        f"> 生成时间：{now}",
        f"> 持仓数量：{len(holdings)}",
        "",
        "## 高相关快讯",
    ]

    if not items:
        lines.append("- 暂无高相关快讯（可提高抓取条数后重试）。")
        return "\n".join(lines)

    for i, it in enumerate(items, 1):
        lines.append(f"### {i}. [{it.show_time}] {it.title}")
        lines.append(f"- 相关性评分：{it.score}")
        lines.append(f"- 优先级：{it.priority}（时效分 {it.freshness_score}）")
        if it.tags:
            lines.append(f"- 标签：{' | '.join(it.tags)}")
        lines.append(f"- 摘要：{it.summary}")
        lines.append("")

    lines.append("## 使用建议")
    lines.append("- 先看`持仓相关`标签，再看`宏观/市场`、`AI/科技`与`产业赛道`标签。")
    lines.append("- 若连续两期都出现同一主题，提升其观察优先级。")
    lines.append("- 对高波动主题（AI、券商、汽车链）优先执行风控纪律。")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch and filter fast news for portfolio and macro relevance")
    parser.add_argument("--holding-md", required=True, help="Path to 我的持仓.md")
    parser.add_argument("--page-size", type=int, default=80, help="Number of latest fast news to fetch")
    parser.add_argument("--top-k", type=int, default=12, help="How many filtered news to keep")
    parser.add_argument("--out-json", required=True, help="Output raw filtered json path")
    parser.add_argument("--out-md", required=True, help="Output markdown brief path")
    args = parser.parse_args()

    holding_path = Path(args.holding_md)
    holdings = load_holdings(holding_path)
    raw_items = fetch_fastnews(args.page_size)
    now = datetime.now()
    scored = [score_item(it, holdings, now) for it in raw_items]
    scored = [it for it in scored if it.score >= 2]
    scored.sort(
        key=lambda x: (x.score, parse_show_time(x.show_time) or datetime.min),
        reverse=True,
    )
    top_items = deduplicate_by_title(scored)[: args.top_k]

    out_json = Path(args.out_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(
        json.dumps(
            [
                {
                    "show_time": it.show_time,
                    "title": it.title,
                    "summary": it.summary,
                    "score": it.score,
                    "priority": it.priority,
                    "freshness_score": it.freshness_score,
                    "tags": it.tags,
                }
                for it in top_items
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    out_md = Path(args.out_md)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text(build_markdown(top_items, holdings), encoding="utf-8")

    print(f"holdings={len(holdings)} fetched={len(raw_items)} selected={len(top_items)}")
    print(f"json={out_json}")
    print(f"md={out_md}")


if __name__ == "__main__":
    main()
