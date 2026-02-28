#!/usr/bin/env python3
"""Fetch macro-liquidity indicators (US/CN) with explicit period comparisons."""

from __future__ import annotations

import csv
import io
import json
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


def load_fred(series: str) -> list[tuple[str, str]]:
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"
    text = requests.get(url, timeout=20).text
    rows = list(csv.DictReader(io.StringIO(text)))
    return [(r["observation_date"], r[series]) for r in rows if r.get(series) not in ("", ".", None)]


def to_float(value: str) -> float:
    return float(value)


def load_eastmoney(report_name: str, sort_col: str = "REPORT_DATE", page_size: int = 3) -> list[dict[str, Any]]:
    params = {
        "reportName": report_name,
        "columns": "ALL",
        "pageNumber": "1",
        "pageSize": str(page_size),
        "sortColumns": sort_col,
        "sortTypes": "-1",
    }
    js = requests.get(EASTMONEY_BASE, params=params, timeout=20).json()
    if not js.get("success"):
        return []
    return js.get("result", {}).get("data", []) or []


def us_block() -> dict[str, Any]:
    result: dict[str, Any] = {}
    for code, name in FRED_SERIES.items():
        vals = load_fred(code)
        latest_date, latest_val = vals[-1]
        prev_date, prev_val = vals[-2]
        latest = to_float(latest_val)
        prev = to_float(prev_val)
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
            d5 = to_float(d5_val)
            d20 = to_float(d20_val)
            item["d5_date"] = d5_date
            item["d5"] = d5
            item["d5_delta"] = latest - d5
            item["d20_date"] = d20_date
            item["d20"] = d20
            item["d20_delta"] = latest - d20
        result[code] = item
    return result


def fetch_fastnews(page_size: int = 200) -> list[dict[str, Any]]:
    params = {
        "client": "web",
        "biz": "web_724",
        "fastColumn": "102,103,104,105",
        "sortEnd": "",
        "pageSize": str(page_size),
    }
    resp = requests.get(FASTNEWS_API, params=params, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
    data = resp.json()
    if str(data.get("code")) != "1":
        return []
    return data.get("data", {}).get("fastNewsList", []) or []


def cn_block() -> dict[str, Any]:
    cn: dict[str, Any] = {}

    money = load_eastmoney("RPT_ECONOMY_CURRENCY_SUPPLY")
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

    rmb_loan = load_eastmoney("RPT_ECONOMY_RMB_LOAN")
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

    cpi = load_eastmoney("RPT_ECONOMY_CPI")
    ppi = load_eastmoney("RPT_ECONOMY_PPI")
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

    rate = load_eastmoney("RPTA_WEB_RATE", sort_col="TRADE_DATE")
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

    shibor = requests.get(
        "https://www.chinamoney.com.cn/ags/ms/cm-u-bk-shibor/ShiborHis?lang=CN",
        timeout=20,
        headers={"User-Agent": "Mozilla/5.0"},
    ).json().get("records", [])
    frr = requests.get(
        "https://www.chinamoney.com.cn/ags/ms/cm-u-bk-currency/FrrHis?lang=CN",
        timeout=20,
        headers={"User-Agent": "Mozilla/5.0"},
    ).json().get("records", [])
    if len(shibor) >= 2 and len(frr) >= 2:
        s_cur, s_prev = shibor[0], shibor[1]
        f_cur, f_prev = frr[0].get("frValueMap", {}), frr[1].get("frValueMap", {})
        shibor_1w = float(s_cur.get("1W"))
        shibor_1w_prev = float(s_prev.get("1W"))
        fdr007 = float(f_cur.get("FDR007")) if f_cur.get("FDR007") else None
        fdr007_prev = float(f_prev.get("FDR007")) if f_prev.get("FDR007") else None
        fr007 = float(f_cur.get("FR007")) if f_cur.get("FR007") else None
        fr007_prev = float(f_prev.get("FR007")) if f_prev.get("FR007") else None
        cn["interbank_rates"] = {
            "latest_date": s_cur.get("showDateCN"),
            "prev_date": s_prev.get("showDateCN"),
            "shibor_1w": shibor_1w,
            "shibor_1w_prev": shibor_1w_prev,
            "shibor_1w_delta": shibor_1w - shibor_1w_prev,
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

    news = fetch_fastnews(240)
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

    out_data = {
        "us": us_block(),
        "cn": cn_block(),
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(out_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved {out}")


if __name__ == "__main__":
    main()
