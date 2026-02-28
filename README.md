# MOS — OpenClaw 投研工作流项目（Public Safe Edition）

> 这是一个**基于 OpenClaw** 的可公开备份版本，来源于 YMOS 的工作流整理。
> 项目固定路径：`/home/pi/tools/openclaw/MOS`

## 先说清楚：MOS 和 OpenClaw 的关系

- MOS 不是独立 App，不是 Web 服务。
- MOS 是一套给 OpenClaw 使用的「数据脚本 + 工作流规则 + 模板目录」。
- 正常使用方式有两种：
  - 在 OpenClaw 对话里用暗号触发流程。
  - 在终端直接运行 `scripts/` 下脚本。
- `OpenClaw/工作流暗号/` 中的文档就是给 OpenClaw Agent 的执行协议。
- `RUNBOOK.md` 是唯一执行源（执行顺序/质量门禁/输出标准都以它为准）。

## 基于 YMOS 的改动（公开版）

- 改为单层目录，项目名统一为 `MOS`。
- `YM-TIB-SKILL` 改为 `MOS-TIB-SKILL`。
- 删除历史运行数据与个人持仓私有内容，改为模板。
- 增加 `.gitignore`，默认忽略私有配置和运行产物。
- 移除 `zhangxinmin / 张新民 / Zhang Xinmin` 命名描述，统一为通用财报分析框架。
- 文档中明确该仓库是 OpenClaw 工作流项目。

## 目录结构

```text
MOS/
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
│   └── financial_report.py
├── MOS-TIB-SKILL/
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
cd /home/pi/tools/openclaw/MOS
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

## 在 OpenClaw 对话里怎么用

在 OpenClaw 对话中可直接触发：

- `跑一下市场洞察`
- `跑一下宏观洞察`
- `跑一下快讯雷达`
- `做个持仓体检`

规则与输出标准见：
- `RUNBOOK.md`
- `OpenClaw/工作流暗号/投研中台暗号.md`
- `OpenClaw/工作流暗号/投资雷达与策略简报暗号.md`
- `MOS-TIB-SKILL/references/INDEX.md`（skill 与提示词总索引）

默认 Skill 路由：
- `跑一下宏观洞察` -> `MOS-TIB-SKILL/references/skills/宏观洞察/SKILL.md`
- `跑一下快讯雷达` -> `MOS-TIB-SKILL/references/skills/快讯雷达/SKILL.md`
- `跑一下市场洞察` -> `MOS-TIB-SKILL/references/skills/市场洞察编排/SKILL.md`（编排 P19 + P20）
- `调研一下 [股票]` / `分析财报 [公司]` -> `MOS-TIB-SKILL/references/skills/个股研究/SKILL.md`

## 运行逻辑（简版）

1. 输入层：脚本抓数据（RSS/API/宏观）
2. 处理层：按暗号文档和 Skill 规则分析
3. 输出层：生成市场洞察、快讯雷达、财报报告等
4. 归档层：结果写入 `OpenClaw/市场洞察报告/` 与 `ai建议/`

## 如何保证提交到 Git 后仍可正常使用

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
