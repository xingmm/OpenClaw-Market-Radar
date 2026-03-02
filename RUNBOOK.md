# OpenClaw-Market-Radar RUNBOOK

## OpenClaw Runtime Context
- OpenClaw-Market-Radar is an OpenClaw workflow project (not a standalone service).
- Project root must be used as current directory: `/home/pi/tools/openclaw/OpenClaw-Market-Radar`.
- Trigger phrases are defined in `OpenClaw/工作流暗号/*.md`; execution quality gates are defined in this RUNBOOK.
- This document is the single source of truth for execution order, output format, and quality gates.

## Public-Safe Preflight
- This repository is a public-safe template based on YMOS.
- Before running portfolio workflows, copy:
  - `OpenClaw/我的持仓与关注点和投资偏好/我的持仓.template.md` -> `OpenClaw/我的持仓与关注点和投资偏好/我的持仓.md`
  - `OpenClaw/我的持仓与关注点和投资偏好/我的投资状态卡.template.md` -> `OpenClaw/我的持仓与关注点和投资偏好/我的投资状态卡.md`
  - `OpenClaw/我的持仓与关注点和投资偏好/我的关联偏好.template.md` -> `OpenClaw/我的持仓与关注点和投资偏好/我的关联偏好.md`
- Do not commit personal holdings, generated radar outputs, or secret keys.

## Goal
Turn OpenClaw-Market-Radar into a repeatable pipeline: input -> analysis -> action.

## User Delivery Rule (mandatory)
- Always return the report body directly in chat.
- Do not reply with only file path/json location as the final user-facing output.
- File saving is allowed for archive, but chat must contain a readable report summary or full report.
- Macro insight output must be "data + reasoning + conclusion"; each conclusion must cite the data used.
- Mandatory full-version output: for `跑一下市场洞察` / `跑一下宏观洞察` / `跑一下快讯雷达`, always output complete sections per template; concise/summary mode is forbidden unless user explicitly asks for a brief.
- Avoid ending with "what to watch/follow" style advice unless explicitly requested.

## Functional Blocks (final scope)
- 市场洞察（合并版：宏观 + 快讯 + 投资映射）
- 宏观洞察（可单独调用）
- 快讯雷达（可单独调用）
- 财报分析
- 消息解读
- 概念解读
- 持仓体检
- 盘面解读（pending user spec）

## Skill Routing (mandatory)
- `跑一下宏观洞察` -> `OCMR-TIB-SKILL/references/skills/宏观洞察/SKILL.md`
- `跑一下快讯雷达` -> `OCMR-TIB-SKILL/references/skills/快讯雷达/SKILL.md`
- `跑一下市场洞察` -> `OCMR-TIB-SKILL/references/skills/市场洞察编排/SKILL.md`（内部组合 P19 + P20）
- `OCMR-TIB-SKILL/references/p13-market-scanner.md` 作为底层扫描能力保留，不作为默认合并输出路由

## Daily Pipeline (fixed order)
1. Market scan
2. Combined market insight (macro + fastnews + investment mapping)
3. Action checklist

---

## Step 1: Market Scan
Commands:
```bash
python3 scripts/fetch_rss.py 1 --output OpenClaw/市场洞察报告/Raw_Data/$(date +%Y-%m)/financial_data_$(date +%Y%m%d).json
python3 scripts/fetch_macro_liquidity.py --out OpenClaw/市场洞察报告/Raw_Data/$(date +%Y-%m)/macro_liquidity_$(date +%Y%m%d).json
```
Output:
- Raw news JSON in `OpenClaw/市场洞察报告/Raw_Data/YYYY-MM/`
- Macro-liquidity JSON in `OpenClaw/市场洞察报告/Raw_Data/YYYY-MM/`
- Internal report in `OpenClaw/市场洞察报告/Internal_Report/YYYY-MM/`

Market Insight v2 structure (mandatory):
1. 全球宏观温度计（美国流动性/中国流动性/黄金油价与美元利率）
2. 宏观边际变化看板（必须是宏观变量，不得用盘面涨跌替代）
   - 必含：美债利率、美元指数/美元强弱、美元兑人民币、黄金、原油
   - 中国流动性六件套（mandatory when data available）:
     - 社融总量 + 结构（居民/企业中长期贷款）
     - M1/M2
     - CPI/PPI
     - 资金利率（DR007/Shibor）
     - 政策利率（MLF/LPR）
     - 财政与信用脉冲（专项债/财政支出节奏）
   - 每项输出：当前值 + 5日变化 + 20日变化 + 数据来源（低频月度数据用“本期 vs 上期”）
   - 美债收益率不得只用上一日对比，必须给出5日/20日趋势对比
3. 流动性传导判断（必须写清传导链条：宏观变量 -> 折现率/风险溢价 -> 资产风格 -> A股主线）
4. A股主线扫描（板块/产业链/主题）
5. 风口分级（I/II/III）
6. 组合映射（对现有持仓影响 + 3个观察信号 + 3条证伪条件）

Quality gates:
- Data count > 0
- Source timestamp within 24h
- Report contains all mandatory sections above
- Every core conclusion includes: evidence data -> reasoning chain -> final conclusion

---

## Step 2: Combined Market Insight (macro + fastnews + investment mapping)
Commands:
```bash
python3 scripts/fetch_macro_liquidity.py --out OpenClaw/市场洞察报告/Raw_Data/$(date +%Y-%m)/macro_liquidity_$(date +%Y%m%d).json
python3 scripts/fetch_fastnews_portfolio.py \
  --holding-md "OpenClaw/我的持仓与关注点和投资偏好/我的持仓.md" \
  --page-size 200 \
  --top-k 20 \
  --out-json "OpenClaw/我的持仓与关注点和投资偏好/ai建议/快讯雷达_$(date +%Y-%m-%d).json" \
  --out-md "OpenClaw/我的持仓与关注点和投资偏好/ai建议/快讯雷达_$(date +%Y-%m-%d).md"
```
Output:
- One user-facing market insight in chat (mandatory)
- Archive files (macro + fastnews + market report)
- Skill orchestration path:
  - P19 宏观洞察 -> P20 快讯雷达 -> P21 合并编排输出

Required sections in final market insight:
- 宏观定价层（中美流动性/通胀/利率/汇率/油金）
- 市场结构层（指数/板块/主题 + 快讯催化）
- 投资执行层（全A股映射 + 个人持仓映射）

Quality gates:
- Must include both `持仓相关` and `宏观/市场` buckets when available
- Must include `AI/科技` bucket check (大模型/机器人/GPU/算力/半导体) when related headlines exist
- Must include `产业赛道` bucket check (新能源/光伏/储能/汽车) when related headlines exist
- Must include an `重要信息清单` section (time + event + one-line impact), not summary-only
- No duplicate headlines in top-k
- Every core conclusion includes: evidence data -> reasoning chain -> final conclusion
- Full-version output is mandatory; missing any required section counts as failed output
- Do not split into separate fast-news/investment reports for user by default

---

## Step 3: Action Checklist (execution layer)
Every cycle must end with:
- Top 3 actions for next session/day
- Top 3 risks
- Top 3 watch triggers
- Next review timestamp

Format:
- One-line per ticker where needed: `持有/观察/减仓评估` + trigger

---

## Data-Integrity Header (mandatory in all reports)
Each report starts with:
- Report period: current / prior / year-end anchors
- Source files + fetch time
- Field-calculation notes
- Missing fields (if any)

---

## Scoring Model (for fast news)
Final score = relevance + impact + freshness
- Relevance: holding-name/sector hit
- Impact: policy/macro/systemic level
- Freshness: time decay by publish time

Priority labels:
- P1: immediate attention
- P2: monitor today
- P3: context only

---

## Financial Analysis Standard (P16)
Mandatory order:
1. Report-period confirmation
2. Data capture checklist
3. Formula substitution
4. Final structured report
5. Review checklist

Hard rules:
- Use consolidated statements only
- Use `OPERATE_COST` (never `TOTAL_OPERATE_COST` for core profit)
- Separate capex from rolling investment cash where possible
- Declare financial-liability scope explicitly

---

## Trigger Phrases
- 跑一下市场洞察（默认触发合并版完整输出）
- 跑一下宏观洞察（单独输出宏观层）
- 跑一下快讯雷达（单独输出快讯层）
- 做个持仓体检
- 分析财报 [公司]
- 解释一下 [财经概念]
- 解读这条消息

---

## Weekly Maintenance
- Re-check scoring keywords in `fetch_fastnews_portfolio.py`
- Review false positives/false negatives in top-k news
- Update portfolio and preference files
- Archive stale action items

---

## Definition of Done
A run is complete only if all are true:
- Data fetched successfully
- Radar reports generated
- Action checklist produced
- Three falsification conditions included
- Data-integrity header present
