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
    bull_pass: bool
    bear_pass: bool
    bull_pass_prev: bool
    bear_pass_prev: bool
    bull_pass_kind: str
    bear_pass_kind: str
    bull_div_remain: int
    bear_div_remain: int


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


def _latest_divergence(rows: List[dict], bullish: bool) -> Tuple[bool, int | None]:
    crosses = _cross_indices(rows, dead_cross=bullish)
    if len(crosses) < 2:
        return False, None
    a0, a1 = crosses[-2], crosses[-1]
    b0, b1 = crosses[-1], len(rows) - 1
    seg1 = rows[a0:a1 + 1]
    seg2 = rows[b0:b1 + 1]
    if not seg1 or not seg2:
        return False, None

    # User-defined rule: all structure comparisons use close price only.
    if bullish:
        p1 = min(x["close"] for x in seg1)
        p2 = min(x["close"] for x in seg2)
        d1 = min(x["dif"] for x in seg1)
        d2 = min(x["dif"] for x in seg2)
        ok = (p2 < p1) and (d2 > d1) and (rows[-1]["macd"] < 0)
        return ok, (b0 if ok else None)
    p1 = max(x["close"] for x in seg1)
    p2 = max(x["close"] for x in seg2)
    d1 = max(x["dif"] for x in seg1)
    d2 = max(x["dif"] for x in seg2)
    ok = (p2 > p1) and (d2 < d1) and (rows[-1]["macd"] > 0)
    return ok, (b0 if ok else None)


def _latest_passivation(rows: List[dict], bullish: bool, lookback: int = 8) -> Tuple[bool, str]:
    if len(rows) < 3:
        return False, ""
    tail = rows[-min(len(rows), lookback):]
    last = tail[-1]
    prev = tail[-2]
    is_pass = False
    if bullish:
        # Bottom passivation: price still weak but downside momentum starts to flatten.
        is_pass = (
            last["macd"] < 0
            and prev["macd"] < 0
            and last["macd"] > prev["macd"]
            and last["dif"] > prev["dif"]
            and last["close"] <= min(x["close"] for x in tail)
        )
    else:
        # Top passivation: price still strong but upside momentum starts to flatten.
        is_pass = (
            last["macd"] > 0
            and prev["macd"] > 0
            and last["macd"] < prev["macd"]
            and last["dif"] < prev["dif"]
            and last["close"] >= max(x["close"] for x in tail)
        )
    if not is_pass:
        return False, ""
    crosses = _cross_indices(rows, dead_cross=bullish)
    if not crosses:
        return True, "隔钝"
    gap = len(rows) - 1 - crosses[-1]
    return True, ("邻钝" if gap <= 1 else "隔钝")


def _remain_bars_from(start_idx: int | None, total_len: int) -> int:
    if start_idx is None:
        return 0
    elapsed = max(0, total_len - 1 - start_idx)
    return max(0, STRUCTURE_IMPACT_BARS - elapsed)


def calc_structure(rows: List[dict]) -> SignalState:
    cur_bull, bull_start = _latest_divergence(rows, bullish=True)
    cur_bear, bear_start = _latest_divergence(rows, bullish=False)
    cur_bull_pass, cur_bull_kind = _latest_passivation(rows, bullish=True)
    cur_bear_pass, cur_bear_kind = _latest_passivation(rows, bullish=False)
    if len(rows) < 40:
        return SignalState(
            cur_bull,
            cur_bear,
            False,
            False,
            cur_bull_pass,
            cur_bear_pass,
            False,
            False,
            cur_bull_kind,
            cur_bear_kind,
            _remain_bars_from(bull_start, len(rows)),
            _remain_bars_from(bear_start, len(rows)),
        )
    prev = rows[:-1]
    prev_bull, _ = _latest_divergence(prev, bullish=True)
    prev_bear, _ = _latest_divergence(prev, bullish=False)
    return SignalState(
        cur_bull,
        cur_bear,
        prev_bull,
        prev_bear,
        cur_bull_pass,
        cur_bear_pass,
        _latest_passivation(prev, bullish=True)[0],
        _latest_passivation(prev, bullish=False)[0],
        cur_bull_kind,
        cur_bear_kind,
        _remain_bars_from(bull_start, len(rows)),
        _remain_bars_from(bear_start, len(rows)),
    )


def _barlastcount(flags: List[bool]) -> int:
    """TongDaXin BARSLASTCOUNT equivalent on current bar."""
    c = 0
    for f in flags:
        c = c + 1 if f else 0
    return c


def calc_td9(rows: List[dict]) -> Dict[str, int]:
    """TD9 setup (TongDaXin style):

    UP_RAW  = BARSLASTCOUNT(C > REF(C,4))
    DOWN_RAW= BARSLASTCOUNT(C < REF(C,4))
    TD high/low count is clipped to 9 for display.
    """
    closes = [r["close"] for r in rows]
    if len(closes) < 5:
        return {"up": 0, "down": 0, "up_raw": 0, "down_raw": 0}

    up_flags: List[bool] = [False, False, False, False]
    down_flags: List[bool] = [False, False, False, False]
    for i in range(4, len(closes)):
        up_flags.append(closes[i] > closes[i - 4])
        down_flags.append(closes[i] < closes[i - 4])

    up_raw = _barlastcount(up_flags)
    down_raw = _barlastcount(down_flags)
    up = min(up_raw, 9) if up_raw > 0 else 0
    down = min(down_raw, 9) if down_raw > 0 else 0

    # Mirror TD display expectation: only one side is active.
    if up > 0:
        down = 0
    elif down > 0:
        up = 0

    return {"up": up, "down": down, "up_raw": up_raw, "down_raw": down_raw}


def td_text(td: Dict[str, int]) -> str:
    if td["up"] > 0:
        return f"高{td['up']}"
    if td["down"] > 0:
        return f"低{td['down']}"
    return "无"


def pct_change(rows: List[dict]) -> float:
    if len(rows) < 2:
        return 0.0
    prev = rows[-2]["close"]
    cur = rows[-1]["close"]
    return 0.0 if prev == 0 else (cur - prev) / prev * 100


def trendline_state_text(prev_close: float, prev_trend: float, cur_close: float, cur_trend: float) -> str:
    if prev_close >= prev_trend and cur_close < cur_trend:
        return "跌破趋势线"
    if prev_close <= prev_trend and cur_close > cur_trend:
        return "突破趋势线"
    return "在趋势线之上" if cur_close >= cur_trend else "在趋势线之下"


def _structure_tag(s: SignalState) -> str:
    if s.bear_div:
        return "顶"
    if s.bull_div:
        return "底"
    return "无"


def index_detail_line(
    name: str,
    rows_daily: List[dict],
    rows_120m: List[dict],
    rows_90m: List[dict],
    rows_60m: List[dict],
) -> str:
    ind_d = add_indicators(rows_daily)
    last = ind_d[-1]
    prev = ind_d[-2] if len(ind_d) >= 2 else ind_d[-1]
    chg = pct_change(rows_daily)
    trend_state = trendline_state_text(prev["close"], prev["ema30"], last["close"], last["ema30"])
    life_state = "在生死线之上" if last["close"] >= last["ema144"] else "在生死线之下"
    gap = abs(last["ema30"] - last["ema144"]) / last["ema144"] * 100

    st_d = calc_structure(ind_d)
    st_120 = calc_structure(add_indicators(rows_120m))
    st_90 = calc_structure(add_indicators(rows_90m))
    st_60 = calc_structure(add_indicators(rows_60m))
    macd_note = (
        f"MACD(日/120/90/60)={_structure_tag(st_d)}/{_structure_tag(st_120)}/"
        f"{_structure_tag(st_90)}/{_structure_tag(st_60)}"
    )

    td_d = calc_td9(rows_daily)
    td_120 = calc_td9(rows_120m)
    td_90 = calc_td9(rows_90m)
    td_60 = calc_td9(rows_60m)
    td_note = (
        f"TD9(日/120/90/60)={td_text(td_d)}|{td_text(td_120)}|"
        f"{td_text(td_90)}|{td_text(td_60)}"
    )

    return (
        f"- {name}: 收盘{last['close']:.2f} 日涨跌{chg:.2f}% | "
        f"趋势线={last['ema30']:.2f} 生死线={last['ema144']:.2f} "
        f"({trend_state},{life_state}; 短长距{gap:.2f}%) | {macd_note} | {td_note}"
    )


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
    if s.bull_pass:
        tags.append(f"底钝化({s.bull_pass_kind})")
    if s.bear_pass:
        tags.append(f"顶钝化({s.bear_pass_kind})")
    if s.bull_div:
        tags.append("底结构")
    if s.bear_div:
        tags.append("顶结构")
    if s.bull_pass and not s.bull_pass_prev:
        tags.append("底钝化出现")
    if s.bear_pass and not s.bear_pass_prev:
        tags.append("顶钝化出现")
    if s.bull_div and not s.bull_div_prev:
        tags.append("底结构形成")
    if s.bear_div and not s.bear_div_prev:
        tags.append("顶结构形成")
    if (not s.bull_pass) and s.bull_pass_prev:
        tags.append("底钝化消失")
    if (not s.bear_pass) and s.bear_pass_prev:
        tags.append("顶钝化消失")
    if (not s.bull_div) and s.bull_div_prev:
        tags.append("底结构消失")
    if (not s.bear_div) and s.bear_div_prev:
        tags.append("顶结构消失")
    if not tags:
        tags.append("无结构信号")
    remain_bits: List[str] = []
    # User rule: once structure is recognized, display full 24-bar impact window.
    bull_remain = STRUCTURE_IMPACT_BARS if s.bull_div else s.bull_div_remain
    bear_remain = STRUCTURE_IMPACT_BARS if s.bear_div else s.bear_div_remain
    if s.bull_div:
        remain_bits.append(f"底结构剩余{bull_remain}根")
    if s.bear_div:
        remain_bits.append(f"顶结构剩余{bear_remain}根")
    remain_txt = "；".join(remain_bits) if remain_bits else "无结构剩余周期"
    return f"- {tf}: {'/'.join(tags)}（{remain_txt}）"


def build_report(out_json: Path, out_md: Path) -> None:
    daily = add_indicators(fetch_kline(SYMBOLS["上证指数"], 240, 260))
    last = daily[-1]
    prev_daily = daily[-2] if len(daily) >= 2 else daily[-1]

    tf_map = {"60m": 60, "90m": 90, "120m": 120, "日线": 240}
    struct_states: Dict[str, SignalState] = {}
    for name, scale in tf_map.items():
        tf_rows = add_indicators(fetch_kline(SYMBOLS["上证指数"], scale, 260))
        struct_states[name] = calc_structure(tf_rows)

    risk_tfs = [k for k, v in struct_states.items() if v.bear_div]
    reduce_layers, reasons = trend_action(last, bool(risk_tfs))

    td_map = {"月线": 240, "周线": 240, "日线": 240, "120m": 120, "90m": 90, "60m": 60}
    td_lines: List[str] = []
    td_up7 = 0
    td_down7 = 0
    for name, scale in td_map.items():
        td = calc_td9(fetch_kline(SYMBOLS["上证指数"], scale, 80))
        txt = f"{name} TD={td_text(td)}"
        if td["up"] >= 7:
            td_up7 += 1
            txt += "（高位7+不追高提示）"
        if td["down"] >= 7:
            td_down7 += 1
            if not risk_tfs:
                txt += "（低位7+可作观察参考）"
        td_lines.append(f"- {txt}")

    sync_lines = []
    for name in ["深证成指", "创业板指", "上证50", "沪深300", "中证500"]:
        rows_d = fetch_kline(SYMBOLS[name], 240, 260)
        rows_120 = fetch_kline(SYMBOLS[name], 120, 260)
        rows_90 = fetch_kline(SYMBOLS[name], 90, 260)
        rows_60 = fetch_kline(SYMBOLS[name], 60, 260)
        sync_lines.append(index_detail_line(name, rows_d, rows_120, rows_90, rows_60))

    trend_gap = abs(last["ema30"] - last["ema144"]) / last["ema144"] * 100
    trend_state = trendline_state_text(prev_daily["close"], prev_daily["ema30"], last["close"], last["ema30"])
    life_state = "在生死线之上" if last["close"] >= last["ema144"] else "在生死线之下"
    macd_summary = "存在风险结构" if risk_tfs else "未见风险结构"
    lines = [
        "# 盘面每日复盘（趋势为王，结构修边）",
        f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## 1) 趋势状态（日线）",
        f"- 上证收盘(最新K): {last['close']:.2f}",
        f"- 趋势线(EMA30): {last['ema30']:.2f}",
        f"- 生死线(EMA144): {last['ema144']:.2f}",
        f"- 短长趋势距离: {trend_gap:.2f}%（<=2%视为接近）",
        f"- 趋势结论: {trend_state}，{life_state}",
        "",
        "## 2) 结构状态（60m/90m/120m/日线）",
        f"- MACD总述: {macd_summary}",
        *[structure_line(k, v) for k, v in struct_states.items()],
        f"- 共振检查: {'存在多周期风险共振' if len(risk_tfs) >= 2 else '无明显风险共振'}",
        "",
        "## 3) 仓位动作建议（总仓位口径）",
        f"- 建议动作: {'减' + str(reduce_layers) + '层' if reduce_layers > 0 else '维持仓位'}",
        f"- 触发依据: {'；'.join(reasons) if reasons else '未触发破趋势与高威胁结构条件'}",
        "",
        "## 4) TD9提示（月/周/日/120/90/60）",
        f"- TD9总述: 高位7+出现{td_up7}个周期，低位7+出现{td_down7}个周期。",
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
