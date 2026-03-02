import importlib.util
import pathlib
import sys
import unittest
from datetime import datetime

ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "fetch_fastnews_portfolio.py"


def load_module():
    spec = importlib.util.spec_from_file_location("fetch_fastnews_portfolio", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TestFastnewsLogic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_module()

    def test_freshness_priority_recent(self):
        now = datetime(2026, 3, 2, 14, 0, 0)
        score, priority = self.mod.freshness_and_priority("2026-03-02 12:30:00", now)
        self.assertEqual(score, 3)
        self.assertEqual(priority, "P1")

    def test_freshness_priority_stale(self):
        now = datetime(2026, 3, 2, 14, 0, 0)
        score, priority = self.mod.freshness_and_priority("2026-02-28 09:00:00", now)
        self.assertEqual(score, 0)
        self.assertEqual(priority, "P3")

    def test_deduplicate_by_title(self):
        item1 = self.mod.NewsItem(
            show_time="2026-03-02 12:00:00",
            title="比亚迪 发布 新技术",
            summary="a",
            score=5,
            priority="P1",
            freshness_score=3,
            tags=[],
        )
        item2 = self.mod.NewsItem(
            show_time="2026-03-02 11:50:00",
            title="比亚迪发布新技术",
            summary="b",
            score=4,
            priority="P1",
            freshness_score=3,
            tags=[],
        )
        item3 = self.mod.NewsItem(
            show_time="2026-03-02 11:00:00",
            title="宁德时代扩产",
            summary="c",
            score=4,
            priority="P2",
            freshness_score=2,
            tags=[],
        )
        deduped = self.mod.deduplicate_by_title([item1, item2, item3])
        self.assertEqual(len(deduped), 2)
        self.assertEqual(deduped[0].title, "比亚迪 发布 新技术")
        self.assertEqual(deduped[1].title, "宁德时代扩产")


if __name__ == "__main__":
    unittest.main()
