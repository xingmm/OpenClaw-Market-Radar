#!/usr/bin/env python3
"""Daily market review using trend + structure rules for SH index."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

import requests

SINA_API = "https://quotes.sina.cn/cn/api/openapi.php/CN_MarketDataService.getKLineData"
SYMBOLS = {
    "上证指数": "sh000001",
    "深证成指": "sz399001",
    "创业板指": "sz399006",
    "上证50": "sh000016",
    "沪深300": "sh000300",
    "中证500": "sh000905",
}

TREND_NEAR_GAP = 0.02
PRICE_NEAR_TREND = 0.015
STRUCTURE_IMPACT_BARS = 24


@dataclass
class SignalState:
    bull_div: bool
    bear_div: bool
    bull_div_prev: bool
    bear_div_prev: bool


def fetch_kline(symbol: str, scale: int, datalen: int) -> List[dict]:
    params = {"symbol": symbol, "scale": str(scale), "ma": "no", "datalen": str(datalen)}
    resp = requests.get(SINA_API, params=params, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    payload = resp.json()
    data = payload.get("result", {}).get("data") or []
    if not data:
        raise RuntimeError(f"No kline data for {symbol} scale={scale}")
    rows: List[dict] = []
    for item in data:
        rows.append(
            {
                "time": item.get("day"),
                "open": float(item.get("open", 0) or 0),
                "high": float(item.get("high", 0) or 0),
                "low": float(item.get("low", 0) or 0),
                "close": float(item.get("close", 0) or 0),
            }
        )
    return rows


def ema(values: List[float], span: int) -> List[float]:
    alpha = 2 / (span + 1)
    out: List[float] = []
    prev = values[0]
    out.append(prev)
    for v in values[1:]:
        prev = alpha * v + (1 - alpha) * prev
        out.append(prev)
    return out


def add_indicators(rows: List[dict]) -> List[dict]:
    closes = [r["close"] for r in rows]
    ema30 = ema(closes, 30)
    ema144 = ema(closes, 144)
    ema12 = ema(closes, 12)
    ema26 = ema(closes, 26)
    dif = [a - b for a, b in zip(ema12, ema26)]
    dea = ema(dif, 9)
    macd = [(d - e) * 2 for d, e in zip(dif, dea)]

    out: List[dict] = []
    for i, r in enumerate(rows):
        rr = dict(r)
        rr.update({"ema30": ema30[i], "ema144": ema144[i], "dif": dif[i], "dea": dea[i], "macd": macd[i]})
        out.append(rr)
    return out


def _cross_indices(rows: List[dict], dead_cross: bool) -> List[int]:
    idx = []
    for i in range(1, len(rows)):
        p_dif, p_dea = rows[i - 1]["dif"], rows[i - 1]["dea"]
        c_dif, c_dea = rows[i]["dif"], rows[i]["dea"]
        if dead_cross and p_dif >= p_dea and c_dif < c_dea:
            idx.append(i)
        if (not dead_cross) and p_dif <= p_dea and c_dif > c_dea:
            idx.append(i)
    return idx


def _latest_divergence(rows: List[dict], bullish: bool) -> bool:
    crosses = _cross_indices(rows, dead_cross=bullish)
    if len(crosses) < 2:
        return False
    a0, a1 = crosses[-2], crosses[-1]
    b0, b1 = crosses[-1], len(rows) - 1
    seg1 = rows[a0:a1 + 1]
    seg2 = rows[b0:b1 + 1]
    if not seg1 or not seg2:
        return False

    if bullish:
        p1 = min(x["low"] for x in seg1)
        p2 = min(x["low"] for x in seg2)
        d1 = min(x["dif"] for x in seg1)
        d2 = min(x["dif"] for x in seg2)
        return (p2 < p1) and (d2 > d1) and (rows[-1]["macd"] < 0)
    p1 = max(x["high"] for x in seg1)
    p2 = max(x["high"] for x in seg2)
    d1 = max(x["dif"] for x in seg1)
    d2 = max(x["dif"] for x in seg2)
    return (p2 > p1) and (d2 < d1) and (rows[-1]["macd"] > 0)


def calc_structure(rows: List[dict]) -> SignalState:
    cur_bull = _latest_divergence(rows, bullish=True)
    cur_bear = _latest_divergence(rows, bullish=False)
    if len(rows) < 40:
        return SignalState(cur_bull, cur_bear, False, False)
    prev = rows[:-1]
    return SignalState(
        cur_bull,
        cur_bear,
        _latest_divergence(prev, bullish=True),
        _latest_divergence(prev, bullish=False),
    )


def calc_td9(rows: List[dict]) -> Dict[str, int]:
    closes = [r["close"] for r in rows]
    up = 0
    down = 0
    for i in range(4, len(closes)):
        if closes[i] > closes[i - 4]:
            up += 1
            down = 0
        elif closes[i] < closes[i - 4]:
            down += 1
            up = 0
        else:
            up = 0
            down = 0
    return {"up": up, "down": down}


def pct_change(rows: List[dict]) -> float:
    if len(rows) < 2:
        return 0.0
    prev = rows[-2]["close"]
    cur = rows[-1]["close"]
    return 0.0 if prev == 0 else (cur - prev) / prev * 100


def trend_action(last: dict, has_risk_structure: bool) -> Tuple[int, List[str]]:
    close = last["close"]
    ema30 = last["ema30"]
    ema144 = last["ema144"]

    break_short = close < ema30
    break_long = close < ema144
    trend_near = abs(ema30 - ema144) / ema144 <= TREND_NEAR_GAP
    near_short = abs(close - ema30) / ema30 <= PRICE_NEAR_TREND
    near_long = abs(close - ema144) / ema144 <= PRICE_NEAR_TREND
    price_near = near_short or near_long

    reduce_layers = 0
    reasons: List[str] = []

    if break_short:
        reduce_layers = max(reduce_layers, 4)
        reasons.append("跌破短期趋势(EMA30)")
    if break_long:
        reduce_layers = max(reduce_layers, 6 if break_short else 2)
        reasons.append("跌破长期趋势(EMA144)")

    if has_risk_structure:
        reasons.append("出现MACD风险结构")
        if trend_near and price_near:
            reduce_layers = max(reduce_layers, 6)
            reasons.append("短长趋势接近且价格靠近趋势")
        elif price_near:
            reduce_layers = max(reduce_layers, 4)
            reasons.append("价格靠近趋势")
        else:
            reasons.append("价格远离趋势，结构仅提示")

    return reduce_layers, reasons


def structure_line(tf: str, s: SignalState) -> str:
    tags: List[str] = []
    if s.bull_div:
        tags.append("底结构")
    if s.bear_div:
        tags.append("顶结构")
    if s.bull_div and not s.bull_div_prev:
        tags.append("底结构形成")
    if s.bear_div and not s.bear_div_prev:
        tags.append("顶结构形成")
    if (not s.bull_div) and s.bull_div_prev:
        tags.append("底结构消失")
    if (not s.bear_div) and s.bear_div_prev:
        tags.append("顶结构消失")
    if not tags:
        tags.append("无结构")
    return f"- {tf}: {'/'.join(tags)}（影响窗口约{STRUCTURE_IMPACT_BARS}根同级别K线）"


def build_report(out_json: Path, out_md: Path) -> None:
    daily = add_indicators(fetch_kline(SYMBOLS["上证指数"], 240, 260))
    last = daily[-1]

    tf_map = {"60m": 60, "90m": 90, "120m": 120, "日线": 240}
    struct_states: Dict[str, SignalState] = {}
    for name, scale in tf_map.items():
        tf_rows = add_indicators(fetch_kline(SYMBOLS["上证指数"], scale, 260))
        struct_states[name] = calc_structure(tf_rows)

    risk_tfs = [k for k, v in struct_states.items() if v.bear_div]
    reduce_layers, reasons = trend_action(last, bool(risk_tfs))

    td_map = {"月线": 240, "周线": 240, "日线": 240, "120m": 120, "90m": 90, "60m": 60}
    td_lines: List[str] = []
    for name, scale in td_map.items():
        td = calc_td9(fetch_kline(SYMBOLS["上证指数"], scale, 80))
        txt = f"{name} TD上计数={td['up']} TD下计数={td['down']}"
        if td["up"] >= 9:
            txt += "（高位不追高提示）"
        if td["down"] >= 9 and not risk_tfs:
            txt += "（低9可作观察参考）"
        td_lines.append(f"- {txt}")

    sync_lines = []
    for name in ["深证成指", "创业板指", "上证50", "沪深300", "中证500"]:
        rows = fetch_kline(SYMBOLS[name], 240, 3)
        sync_lines.append(f"- {name}: 日涨跌 {pct_change(rows):.2f}%")

    trend_gap = abs(last["ema30"] - last["ema144"]) / last["ema144"] * 100
    lines = [
        "# 盘面每日复盘（趋势为王，结构修边）",
        f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## 1) 趋势状态（日线）",
        f"- 上证收盘(最新K): {last['close']:.2f}",
        f"- 短期趋势EMA30: {last['ema30']:.2f}",
        f"- 长期趋势EMA144: {last['ema144']:.2f}",
        f"- 短长趋势距离: {trend_gap:.2f}%（<=2%视为接近）",
        f"- 趋势结论: {'跌破短期趋势' if last['close'] < last['ema30'] else '站上短期趋势'} / {'跌破长期趋势' if last['close'] < last['ema144'] else '站上长期趋势'}",
        "",
        "## 2) 结构状态（60m/90m/120m/日线）",
        *[structure_line(k, v) for k, v in struct_states.items()],
        f"- 共振检查: {'存在多周期风险共振' if len(risk_tfs) >= 2 else '无明显风险共振'}",
        "",
        "## 3) 仓位动作建议（总仓位口径）",
        f"- 建议动作: {'减' + str(reduce_layers) + '层' if reduce_layers > 0 else '维持仓位'}",
        f"- 触发依据: {'；'.join(reasons) if reasons else '未触发破趋势与高威胁结构条件'}",
        "",
        "## 4) TD9提示（月/周/日/120/90/60）",
        *td_lines,
        "- 说明: TD9仅作提示，不作为直接加减仓信号。",
        "",
        "## 5) 次日观察点",
        "- 上证是否重新站回EMA30；若未站回且风险结构延续，优先风控。",
        "- 关注风险结构是否消失（尤其60m/90m）；消失后再评估风险释放。",
        "- 跟踪指数同步性：若上证与其余五指数背离扩大，警惕风格切换。",
        "",
        "## 指数同步校验（辅助）",
        *sync_lines,
    ]

    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text("\n".join(lines), encoding="utf-8")

    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(
        json.dumps(
            {
                "generated_at": datetime.now().isoformat(),
                "main_index": "上证指数",
                "close": last["close"],
                "ema30": last["ema30"],
                "ema144": last["ema144"],
                "trend_gap_pct": trend_gap,
                "risk_structure_tfs": risk_tfs,
                "reduce_layers_total": reduce_layers,
                "reasons": reasons,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate daily market review report")
    parser.add_argument("--out-json", required=True)
    parser.add_argument("--out-md", required=True)
    args = parser.parse_args()

    build_report(Path(args.out_json), Path(args.out_md))
    print(f"json={args.out_json}")
    print(f"md={args.out_md}")


if __name__ == "__main__":
    main()
