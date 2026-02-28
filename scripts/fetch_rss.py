#!/usr/bin/env python3
"""
MOS RSS 数据获取工具（投资场景示例）

【本脚本是投资研究场景的实现示例】
- 数据源：Yongmai 投资洞察博客 RSS + 其他财经 RSS
- 数据类型：免费全文市场洞察、行业动态、宏观经济

【其他场景如何适配】
本脚本是三层架构「第一层：信息输入」的具体实现。
如果你是其他领域的知识工作者，可以参考本脚本的结构，替换为你的 RSS 源：
- 学术研究 → arXiv RSS / Nature/Science RSS
- 产品经理 → Product Hunt RSS / TechCrunch RSS
- 内容创作 → 微博热搜 RSS / 知乎热榜 RSS

核心不变：通过 RSS 自动抓取内容到本地，无需 API Key
核心可变：RSS_SOURCES 字典中的订阅源列表

【投资场景】免费数据源：
https://yongmai.xyz/category/daily-research/feed/
Yongmai 市场洞察日报，每日更新，全文输出。

如需更多投资类 RSS 源，可参考 Yongmai 博客的推荐清单。
"""

import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
import argparse
import json
import ssl
import sys
import os
from datetime import datetime, timedelta, timezone

# 【投资场景】默认使用 Yongmai 市场洞察 RSS
# 【其他场景】修改为你的主要数据源 URL
DEFAULT_RSS_URL = os.getenv(
    "MOS_RSS_DEFAULT_URL",
    "https://yongmai.xyz/category/daily-research/feed/",
)

# ============================================================
# 【投资场景】默认 RSS 数据源
# 【其他场景】修改为你的领域 RSS 订阅源
# ============================================================
RSS_SOURCES = {
    "市场洞察": DEFAULT_RSS_URL,
    "Investing 综合快讯": "https://cn.investing.com/rss/news.rss",
    "FT中文": "http://www.ftchinese.com/rss/news",
    "MarketWatch Top": "https://feeds.content.dowjones.io/public/rss/mw_topstories",
    "CNBC Top": "https://www.cnbc.com/id/100003114/device/rss/rss.html",
}


def fetch_rss(url, days=1):
    """从 RSS 源获取数据"""
    print(f"🚀 正在获取 RSS 数据...")
    print(f"   数据源: {url}")
    print(f"   时间范围: 最近 {days} 天")

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/rss+xml, application/xml, text/xml",
    }

    req = urllib.request.Request(url, headers=headers, method="GET")

    # SSL Context
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    try:
        with urllib.request.urlopen(req, context=ctx, timeout=30) as response:
            xml_content = response.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        print(f"❌ HTTP 错误: {e.code} - {e.reason}")
        return None
    except urllib.error.URLError as e:
        print(f"❌ 网络错误: {e.reason}")
        return None
    except Exception as e:
        print(f"❌ 未知错误: {e}")
        return None

    # 解析 RSS XML
    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError as e:
        print(f"❌ XML 解析错误: {e}")
        return None

    channel = root.find("channel")
    if channel is None:
        print("❌ 未找到 RSS channel")
        return None

    # 计算时间过滤阈值
    cutoff_time = datetime.now(timezone.utc) - timedelta(days=days)

    items = []
    for item in channel.findall("item"):
        title = item.findtext("title", "").strip()
        link = item.findtext("link", "").strip()
        pub_date = item.findtext("pubDate", "").strip()
        description = item.findtext("description", "").strip()

        # 尝试获取全文内容（content:encoded）
        content = ""
        for child in item:
            if "encoded" in child.tag:
                content = (child.text or "").strip()
                break

        # 解析发布时间
        parsed_date = None
        if pub_date:
            try:
                # RSS 标准时间格式: "Mon, 10 Feb 2026 02:00:00 +0000"
                parsed_date = datetime.strptime(
                    pub_date, "%a, %d %b %Y %H:%M:%S %z"
                )
            except ValueError:
                try:
                    parsed_date = datetime.strptime(
                        pub_date, "%a, %d %b %Y %H:%M:%S %Z"
                    )
                    parsed_date = parsed_date.replace(tzinfo=timezone.utc)
                except ValueError:
                    pass

        # 时间过滤
        if parsed_date and parsed_date < cutoff_time:
            continue

        # 提取分类标签
        categories = [
            cat.text for cat in item.findall("category") if cat.text
        ]

        items.append({
            "title": title,
            "link": link,
            "pub_date": pub_date,
            "categories": categories,
            "description": description,
            "content": content if content else description,
        })

    result = {
        "source": url,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "time_range_days": days,
        "count": len(items),
        "data": items,
    }

    return result


def fetch_all_sources(days=1):
    """从所有配置的 RSS 源获取数据"""
    all_items = []

    for name, url in RSS_SOURCES.items():
        print(f"\n📡 [{name}]")
        result = fetch_rss(url, days)
        if result and result.get("data"):
            for item in result["data"]:
                item["source_name"] = name
            all_items.extend(result["data"])
            print(f"   ✅ 获取 {len(result['data'])} 条")
        else:
            print(f"   ⚠️ 未获取到数据")

    return {
        "sources": list(RSS_SOURCES.keys()),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "time_range_days": days,
        "count": len(all_items),
        "data": all_items,
    }


def main():
    parser = argparse.ArgumentParser(
        description="MOS RSS 数据获取工具 - 从 RSS 源获取市场信息"
    )
    parser.add_argument(
        "days",
        type=float,
        nargs="?",
        default=1,
        help="获取最近 N 天的数据（默认: 1）",
    )
    parser.add_argument(
        "--url",
        default=None,
        help="指定单个 RSS 源 URL（不指定则使用全部配置源）",
    )
    parser.add_argument(
        "--output",
        default="financial_data.json",
        help="输出文件路径（默认: financial_data.json）",
    )

    args = parser.parse_args()

    print("=" * 50)
    print("MOS RSS 数据获取工具")
    print("=" * 50)

    if args.url:
        result = fetch_rss(args.url, args.days)
    else:
        result = fetch_all_sources(args.days)

    if result and result.get("count", 0) > 0:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"\n💾 数据已保存: {args.output}")
        print(f"✅ 共获取 {result['count']} 条数据")

        # 分类统计
        if result.get("data"):
            cats = {}
            for item in result["data"]:
                for cat in item.get("categories", ["未分类"]):
                    cats[cat] = cats.get(cat, 0) + 1
            if cats:
                print("\n📁 分类统计:")
                for cat, num in sorted(cats.items()):
                    print(f"   {cat}: {num} 条")
    else:
        print("\n⚠️ 未获取到数据，请检查网络连接和 RSS 源地址")
        sys.exit(1)


if __name__ == "__main__":
    main()
