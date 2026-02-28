---
name: ocmr-skill-index
description: OpenClaw-Market-Radar 技能索引与导航。用于在个股研究、宏观洞察、快讯雷达、市场洞察编排之间选择正确技能入口。
---

# OpenClaw-Market-Radar 技能索引

## 技能地图

- `references/skills/个股研究/SKILL.md`：个股研究、财报分析、概念拆解、消息解读。
- `references/skills/宏观洞察/SKILL.md`：宏观定价层分析与传导链判断。
- `references/skills/快讯雷达/SKILL.md`：快讯分桶、打分与优先级。
- `references/skills/市场洞察编排/SKILL.md`：市场洞察合并编排（宏观 + 快讯）。

## 路由规则

- `跑一下宏观洞察` -> `references/skills/宏观洞察/SKILL.md`
- `跑一下快讯雷达` -> `references/skills/快讯雷达/SKILL.md`
- `跑一下市场洞察` / `跑一下投资雷达` -> `references/skills/市场洞察编排/SKILL.md`
- `调研一下 [股票]` / `分析财报 [公司]` / `解释一下 [财经概念]` / `解读这条消息` -> `references/skills/个股研究/SKILL.md`

## 说明

- 详细输出结构和质量门禁统一以 `../RUNBOOK.md` 为准。
- `references/` 为单一技能与提示词目录；不再使用独立 `skills/` 顶层目录。
- 参考索引见 `references/INDEX.md`（用于快速定位 skill 与 p 提示词）。
