# OpenClaw-Market-Radar

> 一个开源的投研自动化工作流模板仓库：包含数据抓取脚本、分析规则、技能路由和报告模板。
> 不绑定特定机器或目录；文档中的命令均按仓库相对路径组织。

## 项目定位

- 这不是独立 App，也不是 Web 服务。
- 这是「脚本 + 规则 + 模板」型工作流仓库，可用于 OpenClaw 或其他 Agent/CLI 编排场景。
- 覆盖场景包含：市场洞察、宏观跟踪、快讯雷达、盘面复盘（趋势/MACD/TD9）与财报分析。
- 使用方式：
  - 在对话式 Agent 中通过触发词执行（如 OpenClaw）。
  - 在终端直接运行 `scripts/` 下脚本。
- `RUNBOOK.md` 是唯一执行规范（顺序、质量门禁、输出标准）。

## 项目特性

- 可公开备份：私有配置使用模板文件生成。
- 可复现执行：核心流程沉淀在 `RUNBOOK.md` + `OpenClaw/工作流暗号/`。
- 可扩展技能：策略与提示词集中在 `OCMR-TIB-SKILL/`。
- 能力完整：内置盘面解析框架（趋势线、生死线、MACD结构、TD9提示）并输出可执行仓位动作建议。
- 安全默认：`.gitignore` 默认忽略敏感配置与运行产物。

## 目录结构

```text
OpenClaw-Market-Radar/
├── README.md
├── RUNBOOK.md
├── .gitignore
├── .env.example
├── requirements.txt
├── tests/
├── scripts/
│   ├── check_setup.sh
│   ├── fetch_rss.py
│   ├── fetch_data_api.py
│   ├── fetch_macro_liquidity.py
│   ├── fetch_fastnews_portfolio.py
│   ├── financial_report.py
│   └── market_daily_review.py
├── OCMR-TIB-SKILL/
│   ├── SKILL.md
│   └── references/
│       ├── p*.md
│       └── skills/
├── OpenClaw/
│   ├── 工作流暗号/
│   ├── 市场洞察报告/
│   └── 我的持仓与关注点和投资偏好/
└── obsidian投资知识库/
```

## 5 分钟最小可运行流程（终端）

1. 安装依赖

```bash
# 先进入你的项目目录（下面是示例）
cd /path/to/OpenClaw-Market-Radar
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

可选：复制环境变量模板并加载

```bash
cp .env.example .env
source .env
```

2. 初始化本地私有配置（从模板复制）

```bash
cp OpenClaw/我的持仓与关注点和投资偏好/我的持仓.template.md OpenClaw/我的持仓与关注点和投资偏好/我的持仓.md
cp OpenClaw/我的持仓与关注点和投资偏好/我的投资状态卡.template.md OpenClaw/我的持仓与关注点和投资偏好/我的投资状态卡.md
cp OpenClaw/我的持仓与关注点和投资偏好/我的关联偏好.template.md OpenClaw/我的持仓与关注点和投资偏好/我的关联偏好.md
```

3. 运行环境自检

```bash
bash scripts/check_setup.sh
```

4. 跑一轮最小闭环

```bash
python3 scripts/fetch_rss.py 1 --output OpenClaw/市场洞察报告/Raw_Data/$(date +%Y-%m)/financial_data_$(date +%Y%m%d).json
python3 scripts/fetch_macro_liquidity.py --out OpenClaw/市场洞察报告/Raw_Data/$(date +%Y-%m)/macro_liquidity_$(date +%Y%m%d).json
python3 scripts/fetch_fastnews_portfolio.py \
  --holding-md "OpenClaw/我的持仓与关注点和投资偏好/我的持仓.md" \
  --page-size 100 \
  --top-k 12 \
  --out-json "OpenClaw/我的持仓与关注点和投资偏好/ai建议/快讯雷达_$(date +%Y-%m-%d).json" \
  --out-md "OpenClaw/我的持仓与关注点和投资偏好/ai建议/快讯雷达_$(date +%Y-%m-%d).md"
```

可选：跑一轮盘面复盘（趋势+结构+仓位动作）

```bash
python3 scripts/market_daily_review.py \
  --out-json "OpenClaw/市场洞察报告/Internal_Report/$(date +%Y-%m)/盘面复盘_$(date +%Y-%m-%d).json" \
  --out-md "OpenClaw/市场洞察报告/Internal_Report/$(date +%Y-%m)/盘面复盘_$(date +%Y-%m-%d).md"
```

## 在 OpenClaw 对话里怎么用

在 OpenClaw 对话中可直接触发：

- `跑一下市场洞察`
- `跑一下宏观洞察`
- `跑一下快讯雷达`
- `跑一下盘面复盘` / `做今日复盘` / `跑一下盘面解读`
- `做个持仓体检`

规则与输出标准见：
- `RUNBOOK.md`
- `OpenClaw/工作流暗号/投研中台暗号.md`
- `OpenClaw/工作流暗号/投资雷达与策略简报暗号.md`
- `OCMR-TIB-SKILL/references/INDEX.md`（skill 与提示词总索引）

默认 Skill 路由：
- `跑一下宏观洞察` -> `OCMR-TIB-SKILL/references/skills/宏观洞察/SKILL.md`
- `跑一下快讯雷达` -> `OCMR-TIB-SKILL/references/skills/快讯雷达/SKILL.md`
- `跑一下市场洞察` -> `OCMR-TIB-SKILL/references/skills/市场洞察编排/SKILL.md`（编排 P19 + P20）
- `跑一下盘面复盘` / `做今日复盘` -> `OCMR-TIB-SKILL/references/skills/盘面复盘/SKILL.md`（P22）
- `调研一下 [股票]` / `分析财报 [公司]` -> `OCMR-TIB-SKILL/references/skills/个股研究/SKILL.md`

## 运行逻辑（简版）

1. 输入层：脚本抓数据（RSS/API/宏观）
2. 处理层：按暗号文档和 Skill 规则分析
3. 输出层：生成市场洞察、快讯雷达、盘面复盘、财报报告等
4. 归档层：结果写入 `OpenClaw/市场洞察报告/` 与 `ai建议/`

## 开源仓库维护建议

- 文档入口统一：`README.md` + `RUNBOOK.md`。
- `RUNBOOK.md 是唯一执行源`，其他文档不重复维护执行细节。
- 模板齐全：私有文件使用 `*.template.md` 生成。
- 自检脚本：`scripts/check_setup.sh` 可快速发现缺项。
- 安全忽略规则：`.gitignore` 默认忽略私有配置与运行产物。
- 保留示例报告：`OpenClaw/市场洞察报告/Internal_Report/示例_Internal_Report.md`。

## 公开备份安全说明

- 不提交真实持仓、个人偏好、联系人信息。
- 不提交密钥、token、私有地址。
- 不提交 `Raw_Data` 与 `ai建议` 下运行产物。
- 若新增外部 API，请优先用环境变量，不硬编码凭据。

## 参考

- 本项目基于 YMOS 工作流思路整理。
- 许可见 `LICENSE`。
