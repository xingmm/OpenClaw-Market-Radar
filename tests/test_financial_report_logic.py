import importlib.util
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "financial_report.py"


def load_module():
    spec = importlib.util.spec_from_file_location("financial_report", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TestFinancialReportLogic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_module()

    def test_has_numeric_value(self):
        row = {"A": "1.23", "B": "", "C": None, "D": "abc"}
        self.assertTrue(self.mod.has_numeric_value(row, "A"))
        self.assertFalse(self.mod.has_numeric_value(row, "B"))
        self.assertFalse(self.mod.has_numeric_value(row, "C"))
        self.assertFalse(self.mod.has_numeric_value(row, "D"))

    def test_missing_fields(self):
        row = {
            "TOTAL_OPERATE_INCOME": "100",
            "OPERATE_COST": "",
            "OPERATE_TAX_ADD": None,
            "SALE_EXPENSE": "3",
        }
        fields = [
            "TOTAL_OPERATE_INCOME",
            "OPERATE_COST",
            "OPERATE_TAX_ADD",
            "SALE_EXPENSE",
        ]
        missing = self.mod.missing_fields(row, fields)
        self.assertEqual(missing, ["OPERATE_COST", "OPERATE_TAX_ADD"])


if __name__ == "__main__":
    unittest.main()
