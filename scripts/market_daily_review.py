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


def _cross_series(rows: List[dict]) -> Tuple[List[bool], List[bool]]:
    jc0 = [False] * len(rows)
    sc0 = [False] * len(rows)
    jc = [False] * len(rows)
    sc = [False] * len(rows)
    for i in range(1, len(rows)):
        p_dif, p_dea = rows[i - 1]["dif"], rows[i - 1]["dea"]
        c_dif, c_dea = rows[i]["dif"], rows[i]["dea"]
        jc0[i] = p_dif <= p_dea and c_dif > c_dea
        sc0[i] = p_dif >= p_dea and c_dif < c_dea
        mc_pos2 = rows[i]["macd"] > 0 and rows[i - 1]["macd"] > 0
        mc_neg2 = rows[i]["macd"] < 0 and rows[i - 1]["macd"] < 0
        jc[i] = (jc0[i] and mc_pos2) or (i >= 1 and jc0[i - 1] and mc_pos2)
        sc[i] = (sc0[i] and mc_neg2) or (i >= 1 and sc0[i - 1] and mc_neg2)
    return jc, sc


def _last_three_true(flags: List[bool]) -> List[int]:
    idx = [i for i, v in enumerate(flags) if v]
    return idx[-3:]


def _seg_ext(rows: List[dict], start: int, end: int, key: str, use_max: bool) -> float:
    vals = [rows[i][key] for i in range(start, end + 1)]
    return max(vals) if use_max else min(vals)


def _tdx_state(rows: List[dict]) -> Dict[str, object]:
    n = len(rows)
    if n < 20:
        return {
            "bull_pass": False,
            "bear_pass": False,
            "bull_div": False,
            "bear_div": False,
            "bull_pass_kind": "",
            "bear_pass_kind": "",
        }

    t = n - 1
    jc, sc = _cross_series(rows)
    j = _last_three_true(jc)
    s = _last_three_true(sc)

    okjc2, okjc3 = len(j) >= 2, len(j) >= 3
    oksc2, oksc3 = len(s) >= 2, len(s) >= 3

    # Top side (JC segments)
    td = ts = tgn = tgs = False
    if okjc2:
        j1, j2 = j[-1], j[-2]
        ch1 = _seg_ext(rows, j1, t, "close", True)
        dh1 = _seg_ext(rows, j1, t, "dif", True)
        ch2 = _seg_ext(rows, j2, j1 - 1, "close", True)
        dh2 = _seg_ext(rows, j2, j1 - 1, "dif", True)
        td = (
            ch1 > ch2
            and dh1 < dh2
            and rows[t]["macd"] > 0
            and rows[t - 1]["macd"] > 0
            and rows[t]["dif"] >= rows[t - 1]["dif"]
        )
    if okjc3:
        j1, j2, j3 = j[-1], j[-2], j[-3]
        ch1 = _seg_ext(rows, j1, t, "close", True)
        dh1 = _seg_ext(rows, j1, t, "dif", True)
        ch2 = _seg_ext(rows, j2, j1 - 1, "close", True)
        ch3 = _seg_ext(rows, j3, j2 - 1, "close", True)
        dh3 = _seg_ext(rows, j3, j2 - 1, "dif", True)
        ts = (
            ch1 > ch3
            and ch3 > ch2
            and dh1 < dh3
            and rows[t]["macd"] > 0
            and rows[t - 1]["macd"] > 0
            and rows[t]["dif"] >= rows[t - 1]["dif"]
        )
    if t >= 1:
        tgn = rows[t]["dif"] < rows[t - 1]["dif"] and td
        tgs = rows[t]["dif"] < rows[t - 1]["dif"] and ts

    # Bottom side (SC segments)
    bd = bs = bgn = bgs = False
    if oksc2:
        s1, s2 = s[-1], s[-2]
        cl1 = _seg_ext(rows, s1, t, "close", False)
        dl1 = _seg_ext(rows, s1, t, "dif", False)
        cl2 = _seg_ext(rows, s2, s1 - 1, "close", False)
        dl2 = _seg_ext(rows, s2, s1 - 1, "dif", False)
        bd = (
            cl1 < cl2
            and dl1 > dl2
            and rows[t]["macd"] < 0
            and rows[t - 1]["macd"] < 0
            and rows[t]["dif"] <= rows[t - 1]["dif"]
        )
    if oksc3:
        s1, s2, s3 = s[-1], s[-2], s[-3]
        cl1 = _seg_ext(rows, s1, t, "close", False)
        dl1 = _seg_ext(rows, s1, t, "dif", False)
        cl2 = _seg_ext(rows, s2, s1 - 1, "close", False)
        cl3 = _seg_ext(rows, s3, s2 - 1, "close", False)
        dl3 = _seg_ext(rows, s3, s2 - 1, "dif", False)
        bs = (
            cl1 < cl3
            and cl3 < cl2
            and dl1 > dl3
            and rows[t]["macd"] < 0
            and rows[t - 1]["macd"] < 0
            and rows[t]["dif"] <= rows[t - 1]["dif"]
        )
    if t >= 1:
        bgn = rows[t]["dif"] > rows[t - 1]["dif"] and bd
        bgs = rows[t]["dif"] > rows[t - 1]["dif"] and bs

    return {
        "bull_pass": bd or bs,
        "bear_pass": td or ts,
        "bull_div": bgn or bgs,
        "bear_div": tgn or tgs,
        "bull_pass_kind": "邻钝" if bd else ("隔钝" if bs else ""),
        "bear_pass_kind": "邻钝" if td else ("隔钝" if ts else ""),
    }


def calc_structure(rows: List[dict]) -> SignalState:
    cur = _tdx_state(rows)
    prev = _tdx_state(rows[:-1]) if len(rows) > 30 else {
        "bull_pass": False,
        "bear_pass": False,
        "bull_div": False,
        "bear_div": False,
    }

    # Safety merge: keep compatibility with prior close-price divergence signals.
    # This avoids dropping an already-identified daily structure during formula migration.
    legacy_bull_div, _ = _latest_divergence(rows, bullish=True)
    legacy_bear_div, _ = _latest_divergence(rows, bullish=False)
    legacy_bull_pass, legacy_bull_kind = _latest_passivation(rows, bullish=True)
    legacy_bear_pass, legacy_bear_kind = _latest_passivation(rows, bullish=False)

    if len(rows) > 31:
        legacy_prev_bull_div, _ = _latest_divergence(rows[:-1], bullish=True)
        legacy_prev_bear_div, _ = _latest_divergence(rows[:-1], bullish=False)
        legacy_prev_bull_pass, _ = _latest_passivation(rows[:-1], bullish=True)
        legacy_prev_bear_pass, _ = _latest_passivation(rows[:-1], bullish=False)
    else:
        legacy_prev_bull_div = legacy_prev_bear_div = False
        legacy_prev_bull_pass = legacy_prev_bear_pass = False

    cur_bull_div = bool(cur["bull_div"]) or legacy_bull_div
    cur_bear_div = bool(cur["bear_div"]) or legacy_bear_div
    prev_bull_div = bool(prev["bull_div"]) or legacy_prev_bull_div
    prev_bear_div = bool(prev["bear_div"]) or legacy_prev_bear_div
    cur_bull_pass = bool(cur["bull_pass"]) or legacy_bull_pass
    cur_bear_pass = bool(cur["bear_pass"]) or legacy_bear_pass
    prev_bull_pass = bool(prev["bull_pass"]) or legacy_prev_bull_pass
    prev_bear_pass = bool(prev["bear_pass"]) or legacy_prev_bear_pass

    bull_kind = str(cur.get("bull_pass_kind", "")) or legacy_bull_kind
    bear_kind = str(cur.get("bear_pass_kind", "")) or legacy_bear_kind

    return SignalState(
        cur_bull_div,
        cur_bear_div,
        prev_bull_div,
        prev_bear_div,
        cur_bull_pass,
        cur_bear_pass,
        prev_bull_pass,
        prev_bear_pass,
        bull_kind,
        bear_kind,
        STRUCTURE_IMPACT_BARS if cur_bull_div else 0,
        STRUCTURE_IMPACT_BARS if cur_bear_div else 0,
    )


def _barlastcount(flags: List[bool]) -> int:
    """TongDaXin BARSLASTCOUNT equivalent on current bar."""
    c = 0
    for f in flags:
        c = c + 1 if f else 0
    return c


def _td_phase(raw_count: int) -> int:
    """Map continuous setup count to TD9 phase: 1..9 (10->1, 11->2, ...)."""
    if raw_count <= 0:
        return 0
    return ((raw_count - 1) % 9) + 1


def calc_td9(rows: List[dict]) -> Dict[str, int]:
    """TD9 setup aligned to TongDaXin formula style provided by user.

    B  := C < REF(C,4)
    S  := C > REF(C,4)
    JT := BARSLASTCOUNT(B/S)
    Cycle labels repeat every 9 bars (10->1, 11->2 ...).
    """
    closes = [r["close"] for r in rows]
    if len(closes) < 5:
        return {"up": 0, "down": 0, "up_raw": 0, "down_raw": 0}

    up_flags: List[bool] = [False, False, False, False]
    down_flags: List[bool] = [False, False, False, False]
    for i in range(4, len(closes)):
        down_flags.append(closes[i] < closes[i - 4])
        up_flags.append(closes[i] > closes[i - 4])

    up_raw = _barlastcount(up_flags)
    down_raw = _barlastcount(down_flags)

    up = _td_phase(up_raw)
    down = _td_phase(down_raw)

    # One-sided display: only active direction is shown.
    if up_raw > 0:
        down = 0
    elif down_raw > 0:
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
    if (not tags):
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


def structure_event_lines(tf: str, s: SignalState) -> List[str]:
    events: List[str] = []
    if s.bull_pass and not s.bull_pass_prev:
        events.append(f"- {tf}: 底钝化出现")
    if s.bear_pass and not s.bear_pass_prev:
        events.append(f"- {tf}: 顶钝化出现")

    # If same-side structure is active, suppress passivation-disappear noise.
    if (not s.bull_pass) and s.bull_pass_prev and (not s.bull_div):
        events.append(f"- {tf}: 底钝化消失")
    if (not s.bear_pass) and s.bear_pass_prev and (not s.bear_div):
        events.append(f"- {tf}: 顶钝化消失")

    if s.bull_div and not s.bull_div_prev:
        events.append(f"- {tf}: 底结构形成（影响24根同级别K线）")
    if s.bear_div and not s.bear_div_prev:
        events.append(f"- {tf}: 顶结构形成（影响24根同级别K线）")
    if (not s.bull_div) and s.bull_div_prev:
        events.append(f"- {tf}: 底结构消失")
    if (not s.bear_div) and s.bear_div_prev:
        events.append(f"- {tf}: 顶结构消失")
    return events


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
    structure_events: List[str] = []
    for tf, st in struct_states.items():
        structure_events.extend(structure_event_lines(tf, st))

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
        "## 3) MACD事件提示（四周期）",
        *(structure_events if structure_events else ["- 本次无钝化/钝化消失/结构形成/结构消失事件"]),
        "",
        "## 4) 仓位动作建议（总仓位口径）",
        f"- 建议动作: {'减' + str(reduce_layers) + '层' if reduce_layers > 0 else '维持仓位'}",
        f"- 触发依据: {'；'.join(reasons) if reasons else '未触发破趋势与高威胁结构条件'}",
        "",
        "## 5) TD9提示（月/周/日/120/90/60）",
        f"- TD9总述: 高位7+出现{td_up7}个周期，低位7+出现{td_down7}个周期。",
        *td_lines,
        "- 说明: TD9仅作提示，不作为直接加减仓信号。",
        "",
        "## 6) 次日观察点",
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
