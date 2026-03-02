#!/usr/bin/env python3
"""Fetch macro-liquidity indicators (US/CN) with explicit period comparisons."""

from __future__ import annotations

import csv
import io
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

FRED_SERIES = {
    "CPIAUCSL": "US CPI Index",
    "UNRATE": "US Unemployment Rate",
    "PAYEMS": "US Nonfarm Payrolls Level",
    "FEDFUNDS": "US Effective Fed Funds Rate",
    "WALCL": "Fed Balance Sheet (Total Assets, mn USD)",
    "DGS10": "US 10Y Treasury Yield",
}

EASTMONEY_BASE = "https://datacenter-web.eastmoney.com/api/data/v1/get"
FASTNEWS_API = "https://np-weblist.eastmoney.com/comm/web/getFastNewsList"

REQUIRED_METRIC_PATHS = [
    "us.DGS10.latest",
    "us.DGS10.d5",
    "us.DGS10.d20",
    "cn.money_supply.m2_yoy",
    "cn.money_supply.m1_yoy",
    "cn.credit.new_rmb_loan_100m",
    "cn.inflation.cpi_yoy",
    "cn.inflation.ppi_yoy",
    "cn.policy_rates.lpr_1y",
    "cn.policy_rates.lpr_5y",
    "cn.interbank_rates.shibor_1w",
    "cn.fiscal_credit_impulse.fiscal_news_hits",
]

FIELD_CALCULATION_NOTES = {
    "d5_d20_rule": "DGS10 d5/d20 delta = latest - value(5/20 trading days ago) when data available.",
    "dr007_proxy_rule": "Use FDR007 as DR007 proxy from ChinaMoney FR dataset when available.",
    "fiscal_credit_proxy_rule": "Use fast-news keyword hits for fiscal/credit pulse proxy (not official stats).",
}


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_any_date(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y/%m/%d", "%Y/%m"):
        try:
            dt = datetime.strptime(text, fmt)
            if fmt in ("%Y-%m", "%Y/%m"):
                return dt.replace(day=1)
            return dt
        except ValueError:
            continue
    m = re.search(r"(\d{4})", text)
    if m:
        return datetime(int(m.group(1)), 1, 1)
    return None


def choose_anchors(us: dict[str, Any], cn: dict[str, Any]) -> dict[str, Any]:
    candidates = [
        (
            "us.DGS10",
            us.get("DGS10", {}).get("latest_date"),
            us.get("DGS10", {}).get("prev_date"),
        ),
        (
            "cn.policy_rates",
            cn.get("policy_rates", {}).get("latest_date"),
            cn.get("policy_rates", {}).get("prev_date"),
        ),
        (
            "cn.money_supply",
            cn.get("money_supply", {}).get("latest_period"),
            cn.get("money_supply", {}).get("prev_period"),
        ),
        (
            "cn.inflation",
            cn.get("inflation", {}).get("latest_period"),
            cn.get("inflation", {}).get("prev_period"),
        ),
    ]
    current = None
    prior = None
    source = None
    for src, cur, pre in candidates:
        if cur:
            current = cur
            prior = pre
            source = src
            break

    year_end = None
    parsed = parse_any_date(current)
    if parsed:
        year_end = f"{parsed.year - 1}-12-31"

    return {
        "current_anchor": current,
        "prior_anchor": prior,
        "year_end_anchor": year_end,
        "anchor_source": source,
    }


def get_path_value(data: dict[str, Any], path: str) -> Any:
    cur: Any = data
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def is_missing_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    if isinstance(value, list) and len(value) == 0:
        return True
    if isinstance(value, dict) and len(value) == 0:
        return True
    return False


def count_non_null_values(data: Any) -> int:
    if isinstance(data, dict):
        return sum(count_non_null_values(v) for v in data.values())
    if isinstance(data, list):
        return sum(count_non_null_values(v) for v in data)
    return 0 if is_missing_value(data) else 1


def source_within_24h(fetch_events: list[dict[str, Any]], now_dt: datetime) -> bool:
    now_naive = now_dt.replace(tzinfo=None)
    for ev in fetch_events:
        if ev.get("status") != "ok":
            continue
        fetched_at = ev.get("fetched_at")
        parsed = parse_any_date(fetched_at[:10] if isinstance(fetched_at, str) else None)
        if parsed is None:
            return False
        if now_naive - parsed > timedelta(days=1):
            return False
    return True


def build_data_integrity(
    us: dict[str, Any],
    cn: dict[str, Any],
    fetch_events: list[dict[str, Any]],
    generated_at: str,
) -> dict[str, Any]:
    payload = {"us": us, "cn": cn}
    missing = []
    for path in REQUIRED_METRIC_PATHS:
        val = get_path_value(payload, path)
        if is_missing_value(val):
            missing.append(path)

    now_dt = datetime.now(timezone.utc)
    success = [ev for ev in fetch_events if ev.get("status") == "ok"]
    failed = [ev for ev in fetch_events if ev.get("status") != "ok"]
    non_null_count = count_non_null_values(payload)

    return {
        "report_period": {
            **choose_anchors(us, cn),
            "generated_at_utc": generated_at,
        },
        "source_fetch": fetch_events,
        "field_calculation_notes": FIELD_CALCULATION_NOTES,
        "missing_fields": missing,
        "quality_gates": {
            "data_count_gt_zero": non_null_count > 0,
            "non_null_value_count": non_null_count,
            "source_timestamp_within_24h": source_within_24h(success, now_dt),
            "source_success_count": len(success),
            "source_failure_count": len(failed),
            "has_missing_fields": len(missing) > 0,
            "missing_fields_count": len(missing),
        },
    }


def safe_get_json(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    timeout: int = 20,
    headers: dict[str, str] | None = None,
    source_name: str | None = None,
    fetch_events: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    try:
        resp = requests.get(url, params=params, timeout=timeout, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        if fetch_events is not None:
            fetch_events.append(
                {
                    "source": source_name or url,
                    "url": url,
                    "fetched_at": now_utc_iso(),
                    "status": "ok",
                }
            )
        if isinstance(data, dict):
            return data
    except Exception as exc:
        print(f"[WARN] request failed: {url} ({exc})")
        if fetch_events is not None:
            fetch_events.append(
                {
                    "source": source_name or url,
                    "url": url,
                    "fetched_at": now_utc_iso(),
                    "status": "error",
                    "error": str(exc),
                }
            )
    return None


def safe_get_text(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    timeout: int = 20,
    headers: dict[str, str] | None = None,
    source_name: str | None = None,
    fetch_events: list[dict[str, Any]] | None = None,
) -> str | None:
    try:
        resp = requests.get(url, params=params, timeout=timeout, headers=headers)
        resp.raise_for_status()
        if fetch_events is not None:
            fetch_events.append(
                {
                    "source": source_name or url,
                    "url": url,
                    "fetched_at": now_utc_iso(),
                    "status": "ok",
                }
            )
        return resp.text
    except Exception as exc:
        print(f"[WARN] request failed: {url} ({exc})")
        if fetch_events is not None:
            fetch_events.append(
                {
                    "source": source_name or url,
                    "url": url,
                    "fetched_at": now_utc_iso(),
                    "status": "error",
                    "error": str(exc),
                }
            )
        return None


def load_fred(
    series: str,
    fetch_events: list[dict[str, Any]] | None = None,
) -> list[tuple[str, str]]:
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"
    text = safe_get_text(
        url,
        timeout=20,
        source_name=f"FRED:{series}",
        fetch_events=fetch_events,
    )
    if not text:
        return []
    rows = list(csv.DictReader(io.StringIO(text)))
    return [
        (r["observation_date"], r[series])
        for r in rows
        if r.get(series) not in ("", ".", None)
    ]


def to_float(value: str) -> float:
    return float(value)


def load_eastmoney(
    report_name: str,
    sort_col: str = "REPORT_DATE",
    page_size: int = 3,
    fetch_events: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    params = {
        "reportName": report_name,
        "columns": "ALL",
        "pageNumber": "1",
        "pageSize": str(page_size),
        "sortColumns": sort_col,
        "sortTypes": "-1",
    }
    js = safe_get_json(
        EASTMONEY_BASE,
        params=params,
        timeout=20,
        source_name=f"EASTMONEY:{report_name}",
        fetch_events=fetch_events,
    )
    if not js or not js.get("success"):
        return []
    return js.get("result", {}).get("data", []) or []


def us_block(fetch_events: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for code, name in FRED_SERIES.items():
        vals = load_fred(code, fetch_events=fetch_events)
        if len(vals) < 2:
            result[code] = {
                "name": name,
                "error": "insufficient_data",
                "points": len(vals),
            }
            continue

        latest_date, latest_val = vals[-1]
        prev_date, prev_val = vals[-2]
        try:
            latest = to_float(latest_val)
            prev = to_float(prev_val)
        except ValueError:
            result[code] = {
                "name": name,
                "error": "invalid_numeric",
                "latest_raw": latest_val,
                "prev_raw": prev_val,
            }
            continue

        item: dict[str, Any] = {
            "name": name,
            "latest_date": latest_date,
            "latest": latest,
            "prev_date": prev_date,
            "prev": prev,
            "delta": latest - prev,
        }
        if code == "CPIAUCSL" and len(vals) >= 13:
            yprev = to_float(vals[-13][1])
            item["mom_pct"] = (latest / prev - 1) * 100
            item["yoy_pct"] = (latest / yprev - 1) * 100
        if code == "PAYEMS":
            item["mom_change_k"] = latest - prev
        if code == "DGS10" and len(vals) >= 21:
            d5_date, d5_val = vals[-6]
            d20_date, d20_val = vals[-21]
            try:
                d5 = to_float(d5_val)
                d20 = to_float(d20_val)
                item["d5_date"] = d5_date
                item["d5"] = d5
                item["d5_delta"] = latest - d5
                item["d20_date"] = d20_date
                item["d20"] = d20
                item["d20_delta"] = latest - d20
            except ValueError:
                item["d5_date"] = d5_date
                item["d20_date"] = d20_date
                item["d5"] = None
                item["d20"] = None
                item["d5_delta"] = None
                item["d20_delta"] = None
                item["dgs10_trend_note"] = "invalid d5/d20 value"
        result[code] = item
    return result


def fetch_fastnews(
    page_size: int = 200,
    fetch_events: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    params = {
        "client": "web",
        "biz": "web_724",
        "fastColumn": "102,103,104,105",
        "sortEnd": "",
        "pageSize": str(page_size),
    }
    data = safe_get_json(
        FASTNEWS_API,
        params=params,
        timeout=20,
        headers={"User-Agent": "Mozilla/5.0"},
        source_name="EASTMONEY:FASTNEWS",
        fetch_events=fetch_events,
    )
    if not data or str(data.get("code")) != "1":
        return []
    return data.get("data", {}).get("fastNewsList", []) or []


def cn_block(fetch_events: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    cn: dict[str, Any] = {}

    money = load_eastmoney(
        "RPT_ECONOMY_CURRENCY_SUPPLY",
        fetch_events=fetch_events,
    )
    if len(money) >= 2:
        cur, prev = money[0], money[1]
        cn["money_supply"] = {
            "latest_period": cur.get("TIME"),
            "prev_period": prev.get("TIME"),
            "m2_yoy": cur.get("BASIC_CURRENCY_SAME"),
            "m2_yoy_prev": prev.get("BASIC_CURRENCY_SAME"),
            "m1_yoy": cur.get("CURRENCY_SAME"),
            "m1_yoy_prev": prev.get("CURRENCY_SAME"),
            "m0_yoy": cur.get("FREE_CASH_SAME"),
            "m0_yoy_prev": prev.get("FREE_CASH_SAME"),
            "source": "Eastmoney RPT_ECONOMY_CURRENCY_SUPPLY",
        }

    rmb_loan = load_eastmoney("RPT_ECONOMY_RMB_LOAN", fetch_events=fetch_events)
    if len(rmb_loan) >= 2:
        cur, prev = rmb_loan[0], rmb_loan[1]
        cn["credit"] = {
            "latest_period": cur.get("TIME"),
            "prev_period": prev.get("TIME"),
            "new_rmb_loan_100m": cur.get("RMB_LOAN"),
            "new_rmb_loan_100m_prev": prev.get("RMB_LOAN"),
            "new_rmb_loan_yoy": cur.get("RMB_LOAN_SAME"),
            "new_rmb_loan_yoy_prev": prev.get("RMB_LOAN_SAME"),
            "source": "Eastmoney RPT_ECONOMY_RMB_LOAN",
        }

    cpi = load_eastmoney("RPT_ECONOMY_CPI", fetch_events=fetch_events)
    ppi = load_eastmoney("RPT_ECONOMY_PPI", fetch_events=fetch_events)
    if len(cpi) >= 2 and len(ppi) >= 2:
        cpi_cur, cpi_prev = cpi[0], cpi[1]
        ppi_cur, ppi_prev = ppi[0], ppi[1]
        cn["inflation"] = {
            "latest_period": cpi_cur.get("TIME"),
            "prev_period": cpi_prev.get("TIME"),
            "cpi_yoy": cpi_cur.get("NATIONAL_SAME"),
            "cpi_yoy_prev": cpi_prev.get("NATIONAL_SAME"),
            "cpi_mom": cpi_cur.get("NATIONAL_SEQUENTIAL"),
            "cpi_mom_prev": cpi_prev.get("NATIONAL_SEQUENTIAL"),
            "ppi_yoy": ppi_cur.get("BASE_SAME"),
            "ppi_yoy_prev": ppi_prev.get("BASE_SAME"),
            "source": "Eastmoney RPT_ECONOMY_CPI/RPT_ECONOMY_PPI",
        }

    rate = load_eastmoney(
        "RPTA_WEB_RATE",
        sort_col="TRADE_DATE",
        fetch_events=fetch_events,
    )
    if len(rate) >= 2:
        cur, prev = rate[0], rate[1]
        cn["policy_rates"] = {
            "latest_date": cur.get("TRADE_DATE"),
            "prev_date": prev.get("TRADE_DATE"),
            "lpr_1y": cur.get("LPR1Y"),
            "lpr_1y_prev": prev.get("LPR1Y"),
            "lpr_5y": cur.get("LPR5Y"),
            "lpr_5y_prev": prev.get("LPR5Y"),
            "aux_rate_1": cur.get("RATE_1"),
            "aux_rate_2": cur.get("RATE_2"),
            "source": "Eastmoney RPTA_WEB_RATE",
        }

    shibor_js = safe_get_json(
        "https://www.chinamoney.com.cn/ags/ms/cm-u-bk-shibor/ShiborHis?lang=CN",
        timeout=20,
        headers={"User-Agent": "Mozilla/5.0"},
        source_name="CHINAMONEY:SHIBOR",
        fetch_events=fetch_events,
    )
    frr_js = safe_get_json(
        "https://www.chinamoney.com.cn/ags/ms/cm-u-bk-currency/FrrHis?lang=CN",
        timeout=20,
        headers={"User-Agent": "Mozilla/5.0"},
        source_name="CHINAMONEY:FRR",
        fetch_events=fetch_events,
    )
    shibor = (shibor_js or {}).get("records", [])
    frr = (frr_js or {}).get("records", [])
    if len(shibor) >= 2 and len(frr) >= 2:
        s_cur, s_prev = shibor[0], shibor[1]
        f_cur, f_prev = frr[0].get("frValueMap", {}), frr[1].get("frValueMap", {})
        try:
            shibor_1w = float(s_cur.get("1W"))
            shibor_1w_prev = float(s_prev.get("1W"))
        except (TypeError, ValueError):
            shibor_1w = None
            shibor_1w_prev = None
        fdr007 = float(f_cur.get("FDR007")) if f_cur.get("FDR007") else None
        fdr007_prev = float(f_prev.get("FDR007")) if f_prev.get("FDR007") else None
        fr007 = float(f_cur.get("FR007")) if f_cur.get("FR007") else None
        fr007_prev = float(f_prev.get("FR007")) if f_prev.get("FR007") else None
        cn["interbank_rates"] = {
            "latest_date": s_cur.get("showDateCN"),
            "prev_date": s_prev.get("showDateCN"),
            "shibor_1w": shibor_1w,
            "shibor_1w_prev": shibor_1w_prev,
            "shibor_1w_delta": (
                (shibor_1w - shibor_1w_prev)
                if (shibor_1w is not None and shibor_1w_prev is not None)
                else None
            ),
            "fdr007_proxy": fdr007,
            "fdr007_proxy_prev": fdr007_prev,
            "fdr007_proxy_delta": (fdr007 - fdr007_prev) if (fdr007 is not None and fdr007_prev is not None) else None,
            "fr007": fr007,
            "fr007_prev": fr007_prev,
            "fr007_delta": (fr007 - fr007_prev) if (fr007 is not None and fr007_prev is not None) else None,
            "source": "ChinaMoney ShiborHis/FrrHis",
            "note": "FDR007 used as DR007 proxy from available ChinaMoney FR dataset",
        }
    else:
        cn["interbank_rates"] = {
            "dr007": None,
            "shibor_1w": None,
            "source": "pending data source integration",
        }

    news = fetch_fastnews(240, fetch_events=fetch_events)
    fiscal_keys = ["专项债", "特别国债", "财政支出", "财政赤字", "地方债", "基建投资"]
    fiscal_hits: list[dict[str, Any]] = []
    for it in news:
        text = f"{it.get('title','')} {it.get('summary','')}"
        if any(k in text for k in fiscal_keys):
            fiscal_hits.append({
                "showTime": it.get("showTime", ""),
                "title": it.get("title", ""),
            })

    cn["fiscal_credit_impulse"] = {
        "special_bond_issuance": None,
        "fiscal_spending_pace": None,
        "fiscal_news_hits": len(fiscal_hits),
        "fiscal_news_top": fiscal_hits[:5],
        "source": "Eastmoney FastNews keyword proxy (专项债/财政)",
        "note": "Proxy signal only; not official issuance statistics",
    }

    return cn


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    fetch_events: list[dict[str, Any]] = []
    us = us_block(fetch_events=fetch_events)
    cn = cn_block(fetch_events=fetch_events)
    generated_at = now_utc_iso()
    out_data = {
        "data_integrity": build_data_integrity(
            us=us,
            cn=cn,
            fetch_events=fetch_events,
            generated_at=generated_at,
        ),
        "us": us,
        "cn": cn,
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(out_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved {out}")


if __name__ == "__main__":
    main()
