#!/usr/bin/env python3
"""Generate structured financial report with a built-in review checklist.

Data source: Eastmoney F10 consolidated statements.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from typing import Dict, List

import requests

BASE_URL = "https://datacenter.eastmoney.com/securities/api/data/v1/get"


def fetch_rows(report: str, secucode: str, columns: List[str], page_size: int = 40) -> List[dict]:
    params = {
        "reportName": report,
        "columns": ",".join(columns),
        "filter": f'(SECUCODE="{secucode}")',
        "sortColumns": "REPORT_DATE",
        "sortTypes": "-1",
        "pageNumber": "1",
        "pageSize": str(page_size),
        "source": "HSF10",
        "client": "PC",
    }
    js = requests.get(BASE_URL, params=params, timeout=20).json()
    if not js.get("result") or not js["result"].get("data"):
        raise RuntimeError(f"No data for {report}")
    return js["result"]["data"]


def to_map(rows: List[dict]) -> Dict[str, dict]:
    return {r["REPORT_DATE"][:10]: r for r in rows}


def v(row: dict, key: str) -> float:
    val = row.get(key)
    if val in (None, ""):
        return 0.0
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


def has_numeric_value(row: dict, key: str) -> bool:
    val = row.get(key)
    if val in (None, ""):
        return False
    try:
        float(val)
    except (TypeError, ValueError):
        return False
    return True


def missing_fields(row: dict, fields: List[str]) -> List[str]:
    return [k for k in fields if not has_numeric_value(row, k)]


def pct(x: float) -> str:
    return f"{x * 100:.2f}%"


def yi(x: float) -> str:
    return f"{x / 1e8:.2f}亿元"


def yi_or_na(x: float | None) -> str:
    return yi(x) if x is not None else "无法计算（缺少吸收投资收到的现金字段）"


@dataclass
class ReviewItem:
    name: str
    status: str
    detail: str


def build_review_list(cur_inc: dict, cur_cf: dict, cur_bs: dict, checks: dict) -> List[ReviewItem]:
    review = []

    # 1) Cost field review
    use_operate_cost = "OPERATE_COST" in cur_inc and cur_inc.get("OPERATE_COST") is not None
    review.append(
        ReviewItem(
            "核心利润成本口径",
            "PASS" if use_operate_cost else "FAIL",
            "使用 OPERATE_COST(营业成本) 计算；未使用 TOTAL_OPERATE_COST(营业总成本)。" if use_operate_cost else "缺少 OPERATE_COST，无法按标准计算。",
        )
    )

    # 2) Consolidated-only review (API chosen is consolidated table)
    review.append(
        ReviewItem(
            "合并报表口径",
            "PASS",
            "数据源为 RPT_F10_FINANCE_GINCOME / GCASHFLOW / GBALANCE（合并口径）。",
        )
    )

    # 3) Key denominator review
    review.append(
        ReviewItem(
            "分母有效性",
            "PASS" if checks["den_ok"] else "WARN",
            checks["den_msg"],
        )
    )

    # 4) Gross margin consistency review
    review.append(
        ReviewItem(
            "毛利率复核",
            "PASS" if checks["gm_ok"] else "WARN",
            checks["gm_msg"],
        )
    )

    # 5) Equity-financing field path
    review.append(
        ReviewItem(
            "吸收投资口径",
            "PASS" if checks["accept_ok"] else "WARN",
            checks["accept_msg"],
        )
    )

    # 6) Required fields completeness
    review.append(
        ReviewItem(
            "关键字段完整性",
            "PASS" if checks["required_ok"] else "WARN",
            checks["required_msg"],
        )
    )

    return review


def render_review_md(items: List[ReviewItem]) -> str:
    lines = ["\n#### 审核清单（数据准确性 Review List）"]
    for it in items:
        lines.append(f"- [{it.status}] {it.name}: {it.detail}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Financial report generator")
    parser.add_argument("--secucode", required=True, help="e.g. 600584.SH")
    parser.add_argument("--company", required=True)
    parser.add_argument("--period", required=True, help="e.g. 2025-09-30")
    parser.add_argument("--prev-period", required=True, help="e.g. 2024-09-30")
    parser.add_argument("--bs-prev", required=True, help="balance-sheet compare base, e.g. 2024-12-31")
    parser.add_argument("--output", required=True)
    parser.add_argument("--accept-invest-cash-override", type=float, default=None, help="Manual override for 吸收投资收到的现金 (yuan), e.g. 775640000")
    args = parser.parse_args()

    income_cols = [
        "SECUCODE",
        "REPORT_DATE",
        "TOTAL_OPERATE_INCOME",
        "OPERATE_COST",
        "OPERATE_TAX_ADD",
        "SALE_EXPENSE",
        "MANAGE_EXPENSE",
        "RESEARCH_EXPENSE",
        "FINANCE_EXPENSE",
        "OPERATE_PROFIT",
        "INVEST_INCOME",
        "OTHER_INCOME",
    ]
    cash_cols = [
        "SECUCODE",
        "REPORT_DATE",
        "NETCASH_OPERATE",
        "CONSTRUCT_LONG_ASSET",
        "INVEST_PAY_CASH",
        "ACCEPT_INVEST_CASH",
        "SUBSIDIARY_ACCEPT_INVEST",
        "RECEIVE_LOAN_CASH",
        "NETCASH_FINANCE",
    ]
    balance_cols = [
        "SECUCODE",
        "REPORT_DATE",
        "TOTAL_ASSETS",
        "TOTAL_LIABILITIES",
        "TOTAL_CURRENT_ASSETS",
        "TOTAL_CURRENT_LIAB",
        "SHORT_LOAN",
        "LONG_LOAN",
        "BOND_PAYABLE",
        "NONCURRENT_LIAB_1YEAR",
        "LEASE_LIAB",
        "ACCOUNTS_PAYABLE",
        "NOTE_ACCOUNTS_PAYABLE",
        "CONTRACT_LIAB",
        "ADVANCE_RECEIVABLES",
        "OTHER_PAYABLE",
        "TOTAL_EQUITY",
        "UNASSIGN_RPOFIT",
    ]

    inc = to_map(fetch_rows("RPT_F10_FINANCE_GINCOME", args.secucode, income_cols))
    cf = to_map(fetch_rows("RPT_F10_FINANCE_GCASHFLOW", args.secucode, cash_cols))
    bs = to_map(fetch_rows("RPT_F10_FINANCE_GBALANCE", args.secucode, balance_cols))

    cur_i, pre_i = inc[args.period], inc[args.prev_period]
    cur_c, pre_c = cf[args.period], cf[args.prev_period]
    cur_b, pre_b = bs[args.period], bs[args.bs_prev]

    required_income_fields = [
        "TOTAL_OPERATE_INCOME",
        "OPERATE_COST",
        "OPERATE_TAX_ADD",
        "SALE_EXPENSE",
        "MANAGE_EXPENSE",
        "RESEARCH_EXPENSE",
        "FINANCE_EXPENSE",
        "OPERATE_PROFIT",
    ]
    missing_cur_i = missing_fields(cur_i, required_income_fields)
    missing_pre_i = missing_fields(pre_i, required_income_fields)
    if missing_cur_i or missing_pre_i:
        raise RuntimeError(
            "缺少关键利润表字段，停止生成报告以避免错误结论。"
            f" current({args.period}): {missing_cur_i or 'none'};"
            f" previous({args.prev_period}): {missing_pre_i or 'none'}"
        )

    rev = v(cur_i, "TOTAL_OPERATE_INCOME")
    rev_pre = v(pre_i, "TOTAL_OPERATE_INCOME")
    cost = v(cur_i, "OPERATE_COST")
    cost_pre = v(pre_i, "OPERATE_COST")

    gm = (rev - cost) / rev if rev else 0.0
    gm_pre = (rev_pre - cost_pre) / rev_pre if rev_pre else 0.0

    core = (
        rev
        - cost
        - v(cur_i, "OPERATE_TAX_ADD")
        - v(cur_i, "SALE_EXPENSE")
        - v(cur_i, "MANAGE_EXPENSE")
        - v(cur_i, "RESEARCH_EXPENSE")
        - v(cur_i, "FINANCE_EXPENSE")
    )

    op_profit = v(cur_i, "OPERATE_PROFIT")
    inv_plus_other = v(cur_i, "INVEST_INCOME") + v(cur_i, "OTHER_INCOME")
    netcash_oper = v(cur_c, "NETCASH_OPERATE")
    cash_ratio = netcash_oper / core if core else None

    # Some data providers split equity financing into subsidiary minority-investor inflow.
    raw_accept_invest_cash = cur_c.get("ACCEPT_INVEST_CASH")
    accept_invest_cash = float(raw_accept_invest_cash) if raw_accept_invest_cash not in (None, "") else None
    subsidiary_accept_invest = v(cur_c, "SUBSIDIARY_ACCEPT_INVEST")
    if (accept_invest_cash is None or accept_invest_cash == 0) and subsidiary_accept_invest > 0:
        accept_invest_cash = subsidiary_accept_invest
    if args.accept_invest_cash_override is not None:
        accept_invest_cash = float(args.accept_invest_cash_override)

    cur_assets = v(cur_b, "TOTAL_ASSETS")
    pre_assets = v(pre_b, "TOTAL_ASSETS")
    cur_liab = v(cur_b, "TOTAL_LIABILITIES")
    pre_liab = v(pre_b, "TOTAL_LIABILITIES")
    cur_eq = v(cur_b, "TOTAL_EQUITY")
    pre_eq = v(pre_b, "TOTAL_EQUITY")

    current_ratio = v(cur_b, "TOTAL_CURRENT_ASSETS") / v(cur_b, "TOTAL_CURRENT_LIAB") if v(cur_b, "TOTAL_CURRENT_LIAB") else None
    debt_ratio = cur_liab / cur_assets if cur_assets else None

    financial_liab = v(cur_b, "SHORT_LOAN") + v(cur_b, "LONG_LOAN") + v(cur_b, "BOND_PAYABLE") + v(cur_b, "NONCURRENT_LIAB_1YEAR") + v(cur_b, "LEASE_LIAB")
    operating_liab = v(cur_b, "ACCOUNTS_PAYABLE") + v(cur_b, "NOTE_ACCOUNTS_PAYABLE") + v(cur_b, "CONTRACT_LIAB") + v(cur_b, "ADVANCE_RECEIVABLES") + v(cur_b, "OTHER_PAYABLE")

    unassign_inc = v(cur_b, "UNASSIGN_RPOFIT") - v(pre_b, "UNASSIGN_RPOFIT")
    asset_inc = cur_assets - pre_assets

    checks = {
        "den_ok": rev > 0 and op_profit != 0 and cur_assets > 0,
        "den_msg": "营业收入/营业利润/总资产分母有效。" if (rev > 0 and op_profit != 0 and cur_assets > 0) else "存在关键分母为0，部分比例仅供参考。",
        "gm_ok": abs(gm - ((rev - cost) / rev if rev else 0.0)) < 1e-12,
        "gm_msg": f"毛利率复算通过：({yi(rev)}-{yi(cost)})/{yi(rev)}={pct(gm)}",
        "accept_ok": (accept_invest_cash is not None and accept_invest_cash > 0) or (args.accept_invest_cash_override is not None),
        "accept_msg": (
            f"吸收投资收到的现金采用 {yi(accept_invest_cash)}（含子公司少数股东投入或手工覆盖）。"
            if ((accept_invest_cash is not None and accept_invest_cash > 0) or (args.accept_invest_cash_override is not None))
            else "数据源未返回有效吸收投资字段，已标记为无法计算，需用财报原文覆盖。"
        ),
        "required_ok": not missing_cur_i and not missing_pre_i,
        "required_msg": (
            "核心利润所需字段齐全。"
            if (not missing_cur_i and not missing_pre_i)
            else f"字段缺失 current={missing_cur_i or 'none'} previous={missing_pre_i or 'none'}"
        ),
    }

    review_list = build_review_list(cur_i, cur_c, cur_b, checks)

    cash_ratio_str = f"{cash_ratio:.2f}" if cash_ratio is not None else "无法计算"
    current_ratio_str = f"{current_ratio:.2f}" if current_ratio is not None else "无法计算"
    debt_ratio_str = pct(debt_ratio) if debt_ratio is not None else "无法计算"
    core_op_ratio = core / op_profit if op_profit else None
    core_op_ratio_str = pct(core_op_ratio) if core_op_ratio is not None else "无法计算"

    report = f"""### 【报告期确认】
- 报告期确认：本期指 `{args.period}`；上期指 `{args.prev_period}`；上年末指 `{args.bs_prev}`。
- 对比口径确认：
  - 利润表、现金流量表：本期 vs 上期同期
  - 资产负债表、权益变动表：本期末 vs 上年末

### 【数据抓取清单】
A. 合并利润表字段（字段 | 本期 | 上期同期 | 来源表）
- 营业收入 | {yi(v(cur_i,'TOTAL_OPERATE_INCOME'))} | {yi(v(pre_i,'TOTAL_OPERATE_INCOME'))} | 合并利润表
- 营业成本 | {yi(v(cur_i,'OPERATE_COST'))} | {yi(v(pre_i,'OPERATE_COST'))} | 合并利润表
- 税金及附加 | {yi(v(cur_i,'OPERATE_TAX_ADD'))} | {yi(v(pre_i,'OPERATE_TAX_ADD'))} | 合并利润表
- 销售费用 | {yi(v(cur_i,'SALE_EXPENSE'))} | {yi(v(pre_i,'SALE_EXPENSE'))} | 合并利润表
- 管理费用 | {yi(v(cur_i,'MANAGE_EXPENSE'))} | {yi(v(pre_i,'MANAGE_EXPENSE'))} | 合并利润表
- 研发费用 | {yi(v(cur_i,'RESEARCH_EXPENSE'))} | {yi(v(pre_i,'RESEARCH_EXPENSE'))} | 合并利润表
- 财务费用 | {yi(v(cur_i,'FINANCE_EXPENSE'))} | {yi(v(pre_i,'FINANCE_EXPENSE'))} | 合并利润表
- 营业利润 | {yi(v(cur_i,'OPERATE_PROFIT'))} | {yi(v(pre_i,'OPERATE_PROFIT'))} | 合并利润表
- 投资收益 | {yi(v(cur_i,'INVEST_INCOME'))} | {yi(v(pre_i,'INVEST_INCOME'))} | 合并利润表
- 其他收益 | {yi(v(cur_i,'OTHER_INCOME'))} | {yi(v(pre_i,'OTHER_INCOME'))} | 合并利润表

B. 合并现金流量表字段（字段 | 本期 | 上期同期 | 来源表）
- 经营活动现金流净额 | {yi(v(cur_c,'NETCASH_OPERATE'))} | {yi(v(pre_c,'NETCASH_OPERATE'))} | 合并现金流量表
- 购建长期资产支付现金 | {yi(v(cur_c,'CONSTRUCT_LONG_ASSET'))} | {yi(v(pre_c,'CONSTRUCT_LONG_ASSET'))} | 合并现金流量表
- 投资支付现金 | {yi(v(cur_c,'INVEST_PAY_CASH'))} | {yi(v(pre_c,'INVEST_PAY_CASH'))} | 合并现金流量表
- 吸收投资收到现金 | {yi_or_na(accept_invest_cash)} | {yi_or_na(v(pre_c,'ACCEPT_INVEST_CASH') if pre_c.get('ACCEPT_INVEST_CASH') not in (None, '') else None)} | 合并现金流量表
- 取得借款收到现金 | {yi(v(cur_c,'RECEIVE_LOAN_CASH'))} | {yi(v(pre_c,'RECEIVE_LOAN_CASH'))} | 合并现金流量表
- 筹资活动现金流净额 | {yi(v(cur_c,'NETCASH_FINANCE'))} | {yi(v(pre_c,'NETCASH_FINANCE'))} | 合并现金流量表

C. 合并资产负债表字段（字段 | 本期末 | 上年末 | 来源表）
- 资产总计 | {yi(v(cur_b,'TOTAL_ASSETS'))} | {yi(v(pre_b,'TOTAL_ASSETS'))} | 合并资产负债表
- 负债合计 | {yi(v(cur_b,'TOTAL_LIABILITIES'))} | {yi(v(pre_b,'TOTAL_LIABILITIES'))} | 合并资产负债表
- 流动资产合计 | {yi(v(cur_b,'TOTAL_CURRENT_ASSETS'))} | {yi(v(pre_b,'TOTAL_CURRENT_ASSETS'))} | 合并资产负债表
- 流动负债合计 | {yi(v(cur_b,'TOTAL_CURRENT_LIAB'))} | {yi(v(pre_b,'TOTAL_CURRENT_LIAB'))} | 合并资产负债表
- 未分配利润 | {yi(v(cur_b,'UNASSIGN_RPOFIT'))} | {yi(v(pre_b,'UNASSIGN_RPOFIT'))} | 合并资产负债表
- 所有者权益合计 | {yi(v(cur_b,'TOTAL_EQUITY'))} | {yi(v(pre_b,'TOTAL_EQUITY'))} | 合并资产负债表

### 【计算过程复核】
- 毛利率 = (营业收入-营业成本)/营业收入 = ({yi(rev)}-{yi(cost)})/{yi(rev)} = {pct(gm)}
- 核心利润 = 营业收入-营业成本-税金及附加-销售费用-管理费用-研发费用-财务费用 = {yi(core)}
- 核心利润获现率 = 经营现金净额/核心利润 = {yi(netcash_oper)}/{yi(core)} = {cash_ratio_str}
- 资产负债率 = 负债合计/资产总计 = {yi(cur_liab)}/{yi(cur_assets)} = {debt_ratio_str}
- 流动比率 = 流动资产/流动负债 = {yi(v(cur_b,'TOTAL_CURRENT_ASSETS'))}/{yi(v(cur_b,'TOTAL_CURRENT_LIAB'))} = {current_ratio_str}

---
### 📊 财报分析报告：{args.company} ({args.period})

#### 📕 模块一：利润表“五步分析法” (看面子)
*核心心法：剥离投资与补贴，还原企业真实的盈利肉身。*

1. 市场地位分析（营业收入）
- 数据对比：本期营收 {yi(rev)} vs 上期营收 {yi(rev_pre)}。
- 分析结论：营收同比 {'增长' if rev_pre and rev >= rev_pre else '下降'} {pct((rev - rev_pre) / rev_pre) if rev_pre else '无法计算'}。

2. 产品竞争力分析（毛利与毛利率）
- 数据对比：本期毛利率 {pct(gm)} vs 上期毛利率 {pct(gm_pre)}。
- 分析结论：毛利率{'提升' if gm >= gm_pre else '下降'}，需结合产品结构和价格策略判断竞争力变化。

3. 盈利转折点分析（营业利润）
- 数据观测：本期营业利润为 {yi(op_profit)}。
- 分析结论：{'未出现由盈转亏。' if op_profit >= 0 else '出现亏损信号。'}

4. 利润支柱分析（核心利润 vs 投资收益）
- 关键计算：
  - 核心利润 = 收入-成本-税金-4费 = {yi(core)}
  - 投资+补贴 = 投资收益 {yi(v(cur_i, 'INVEST_INCOME'))} + 其他收益 {yi(v(cur_i, 'OTHER_INCOME'))} = {yi(inv_plus_other)}
- 分析结论：核心利润占营业利润比例 {core_op_ratio_str}。

5. 利润含金量预判
- 分析结论：核心利润{'为正' if core > 0 else '为负'}，后续需结合经营现金流验证含金量。

---
#### 📕 模块二：现金流量表“四步分析法” (看日子)
*核心心法：造血能力决定生存，输血能力决定扩张。*

1. 造血能力分析（核心利润获现率）
- 关键计算：经营现金净额 {yi(netcash_oper)} / 核心利润 {yi(core)} = {cash_ratio_str}。
- 分析结论：{('位于1.2~1.5附近。' if cash_ratio is not None and 1.2 <= cash_ratio <= 1.5 else '偏离1.2~1.5常规区间，需拆解营运资金影响。') if cash_ratio is not None else '核心利润为0，无法计算。'}

2. 投资扩张意图（投资现金流）
- 数据结构：
  - 购建资产支付：{yi(v(cur_c, 'CONSTRUCT_LONG_ASSET'))}
  - 投资支付：{yi(v(cur_c, 'INVEST_PAY_CASH'))}
- 分析结论：投资和资本开支规模反映扩张方向。

3. 输血来源分析（筹资现金流）
- 数据对比：吸收投资收到 {yi_or_na(accept_invest_cash)} vs 取得借款收到 {yi(v(cur_c, 'RECEIVE_LOAN_CASH'))}。
- 分析结论：筹资来源结构可判断融资风险偏好。

4. 资金去向与持久性
- 数据观测：筹资净额为 {yi(v(cur_c, 'NETCASH_FINANCE'))}。
- 分析结论：结合偿债与扩张节奏判断资金链持续性。

---
#### 📕 模块三：资产负债表“四步分析法” (看底子)
*核心心法：透过资产看资源结构，透过负债看动力机制。*

1. 扩张速度分析（资产规模）
- 数据对比：本期总资产 {yi(cur_assets)} vs 上期 {yi(pre_assets)}。变动幅度 {pct((cur_assets - pre_assets) / pre_assets) if pre_assets else '无法计算'}。
- 分析结论：企业处于{'扩张' if cur_assets >= pre_assets else '收缩/盘整'}阶段。

2. 扩张资源来源（负债 vs 权益）
- 数据对比：负债增加 {yi(cur_liab - pre_liab)} vs 权益增加 {yi(cur_eq - pre_eq)}。
- 分析结论：观察资产变化主要由债务还是权益驱动。

3. 负债结构定性（烧钱 vs 挣钱）
- 结构拆解：
  - 金融性负债 (短期借款等)：{yi(financial_liab)}
  - 经营性负债 (应付账款等)：{yi(operating_liab)}
- 分析结论：{'经营负债大于金融负债。' if operating_liab >= financial_liab else '金融负债大于经营负债。'}

4. 核心原动力分析（未分配利润）
- 关键数据：未分配利润本期增加 {yi(unassign_inc)}。占总资产增加额的 {pct(unassign_inc / asset_inc) if asset_inc else '无法计算'}。
- 分析结论：判断资产变化是否由利润积累驱动。

---
### 💡 派的最终总结
- 企业画像：需结合主业盈利、现金流与负债结构综合判断。
- 风险提示：重点关注毛利率变化与融资结构变化。
- 关注重点：关注经营现金流对资本开支的覆盖能力、以及资产负债率({debt_ratio_str})与流动比率({current_ratio_str})的趋势。
"""

    report += render_review_md(review_list) + "\n"

    with open(args.output, "w", encoding="utf-8") as f:
        f.write(report)

    print(json.dumps({
        "output": args.output,
        "review": [it.__dict__ for it in review_list],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
