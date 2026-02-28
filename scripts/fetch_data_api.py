#!/usr/bin/env python3
"""
MOS API 数据获取工具（投资场景示例）

【本脚本是投资研究场景的实现示例】
- 数据源：Yongmai 投资情报 API
- 数据类型：中美股市、宏观经济、科技动态、加密货币

【其他场景如何适配】
本脚本是三层架构「第一层：信息输入」的具体实现。
如果你是其他领域的知识工作者，可以参考本脚本的结构，替换为你的 API：
- 学术研究 → Semantic Scholar API / PubMed API
- 产品经理 → Product Hunt API / App Annie API
- 内容创作 → Twitter API / Reddit API

核心不变：通过配置化的脚本自动拉取数据到本地
核心可变：API endpoint、数据格式、存储路径

获取投资数据 API Key：https://yongmai.xyz
"""

import urllib.request
import urllib.parse
import urllib.error
import argparse
import json
import ssl
import sys
import os

# ============================================================
# 优先从环境变量读取配置
# - MOS_API_KEY: API Key
# - MOS_API_URL: API endpoint (optional)
# ============================================================
API_KEY = os.getenv("MOS_API_KEY", "").strip()

# ============================================================
# 【投资场景】API 配置
# 【其他场景】修改为你的 API endpoint 和参数
# ============================================================
API_URL = os.getenv("MOS_API_URL", "https://yongmai.xyz/wp-json/tib/v1/reports").strip()

# 【投资场景】默认分类
# 【其他场景】修改为你的数据分类（论文类型、产品类别等）
CATEGORIES = [
    "#中国股市",
    "#美国股市",
    "#Crypto",
    "#宏观经济",
    "#科技动态",
    "#个人精选"
]


def check_api_key():
    """检查 API Key 是否已配置"""
    if not API_KEY or API_KEY == "your_api_key_here":
        print("=" * 50)
        print("⚠️  API Key 未配置")
        print("=" * 50)
        print()
        print("你需要一个 API Key 才能使用此脚本。")
        print()
        print("📡 获取 API Key：")
        print("   https://yongmai.xyz")
        print()
        print("🆓 免费替代方案：")
        print("   使用 fetch_rss.py 通过免费 RSS 订阅获取数据")
        print("   python3 scripts/fetch_rss.py 1 --output output.json")
        print()
        print("配置方法：")
        print("   export MOS_API_KEY='你的Key'")
        print("   或在项目根目录创建 .env 后手动 source")
        print("   source .env")
        print()
        sys.exit(1)


def fetch_reports(time_value):
    """从 API 获取报告数据"""
    print(f"🚀 正在获取 API 数据...")
    print(f"   接口: {API_URL}")
    print(f"   时间范围: 最近 {time_value} 天")

    # 构建 query parameters
    params = {
        'time_value': time_value,
        'categories': ','.join(CATEGORIES)
    }
    query_string = urllib.parse.urlencode(params)
    full_url = f"{API_URL}?{query_string}"

    # Bearer Token 认证
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "User-Agent": "MOS/1.0",
        "Accept": "application/json"
    }

    req = urllib.request.Request(full_url, headers=headers, method='GET')

    # SSL Context
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    try:
        with urllib.request.urlopen(req, context=ctx, timeout=30) as response:
            response_text = response.read().decode('utf-8')

            try:
                data = json.loads(response_text)

                # 打印限流信息
                if 'rate_limit' in data:
                    rl = data['rate_limit']
                    print(f"\n📊 API 配额: {rl['used']}/{rl['limit']} "
                          f"(剩余 {rl['remaining']} 次)")

                return data
            except json.JSONDecodeError:
                print("❌ JSON 解析失败")
                print("响应内容:", response_text[:500])
                return None

    except urllib.error.HTTPError as e:
        print(f"❌ HTTP 错误: {e.code} - {e.reason}")
        if e.code == 401:
            print("\n🔑 API Key 无效或已过期")
            print("   请前往 https://yongmai.xyz 检查你的订阅状态")
        elif e.code == 429:
            print("\n⏳ API 调用次数已达上限，请稍后再试")
        try:
            error_body = e.read().decode('utf-8')
            print(f"   详情: {error_body[:500]}")
        except:
            pass
        return None
    except urllib.error.URLError as e:
        print(f"❌ 网络错误: {e.reason}")
        return None
    except Exception as e:
        print(f"❌ 未知错误: {e}")
        return None


def main():
    parser = argparse.ArgumentParser(
        description="MOS API 数据获取工具 - 需要 API Key"
    )
    parser.add_argument(
        "time_value",
        type=float,
        nargs='?',
        default=1,
        help="获取最近 N 天的数据（默认: 1）"
    )
    parser.add_argument(
        "--output",
        default="financial_data.json",
        help="输出文件路径（默认: financial_data.json）"
    )

    args = parser.parse_args()

    print("=" * 50)
    print("MOS API 数据获取工具")
    print("=" * 50)

    # 检查 API Key
    check_api_key()

    result = fetch_reports(args.time_value)

    if result:
        # 检查 API 错误
        if isinstance(result, dict) and 'code' in result and 'message' in result:
            print(f"❌ API 错误: {result['message']}")
            sys.exit(1)

        # 保存文件
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"\n💾 数据已保存: {args.output}")

        count = result.get('count', 'N/A') if isinstance(result, dict) else 'N/A'
        print(f"✅ 共获取 {count} 条数据")

        # 分类统计
        if isinstance(result, dict) and 'data' in result:
            categories = {}
            for item in result['data']:
                cat = item.get('category', '未分类')
                categories[cat] = categories.get(cat, 0) + 1

            if categories:
                print("\n📁 分类统计:")
                for cat, num in sorted(categories.items()):
                    print(f"   {cat}: {num} 条")
    else:
        print("\n❌ 数据获取失败")
        print("💡 如果反复失败，可以尝试免费的 RSS 方式：")
        print("   python3 scripts/fetch_rss.py 1 --output output.json")
        sys.exit(1)


if __name__ == "__main__":
    main()
