import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class TestProjectSmoke(unittest.TestCase):
    def test_core_files_exist(self):
        required = [
            ROOT / "README.md",
            ROOT / "RUNBOOK.md",
            ROOT / "requirements.txt",
            ROOT / ".env.example",
            ROOT / "OCMR-TIB-SKILL" / "references" / "INDEX.md",
            ROOT / "scripts" / "fetch_rss.py",
            ROOT / "scripts" / "fetch_data_api.py",
            ROOT / "scripts" / "fetch_macro_liquidity.py",
            ROOT / "scripts" / "fetch_fastnews_portfolio.py",
            ROOT / "scripts" / "financial_report.py",
        ]
        for path in required:
            self.assertTrue(path.exists(), f"missing: {path}")

    def test_runbook_has_skill_routing(self):
        text = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
        self.assertIn("## Skill Routing (mandatory)", text)
        self.assertIn("references/skills/宏观洞察/SKILL.md", text)
        self.assertIn("references/skills/快讯雷达/SKILL.md", text)
        self.assertIn("references/skills/市场洞察编排/SKILL.md", text)

    def test_split_skills_have_valid_frontmatter(self):
        skill_paths = [
            ROOT / "OCMR-TIB-SKILL" / "references" / "skills" / "个股研究" / "SKILL.md",
            ROOT / "OCMR-TIB-SKILL" / "references" / "skills" / "宏观洞察" / "SKILL.md",
            ROOT / "OCMR-TIB-SKILL" / "references" / "skills" / "快讯雷达" / "SKILL.md",
            ROOT / "OCMR-TIB-SKILL" / "references" / "skills" / "市场洞察编排" / "SKILL.md",
        ]
        for path in skill_paths:
            text = path.read_text(encoding="utf-8")
            self.assertTrue(text.startswith("---\n"), f"invalid frontmatter start: {path}")
            self.assertRegex(text, r"\nname:\s*[^\n]+")
            self.assertRegex(text, r"\ndescription:\s*[^\n]+")

    def test_single_source_declared(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("RUNBOOK.md 是唯一执行源", readme)

    def test_route_docs_declare_runbook_authority(self):
        docs = [
            ROOT / "OpenClaw" / "工作流暗号" / "投研中台暗号.md",
            ROOT / "OpenClaw" / "工作流暗号" / "投资雷达与策略简报暗号.md",
        ]
        for path in docs:
            text = path.read_text(encoding="utf-8")
            self.assertIn("RUNBOOK.md 是唯一执行源", text, f"missing authority statement: {path}")


if __name__ == "__main__":
    unittest.main()
