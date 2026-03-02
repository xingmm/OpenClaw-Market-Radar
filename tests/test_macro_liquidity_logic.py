import importlib.util
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "fetch_macro_liquidity.py"


def load_module():
    spec = importlib.util.spec_from_file_location("fetch_macro_liquidity", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TestMacroLiquidityIntegrity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_module()

    def sample_us_cn(self):
        us = {
            "DGS10": {
                "latest_date": "2026-03-02",
                "latest": 4.1,
                "prev_date": "2026-03-01",
                "prev": 4.0,
                "d5": 3.9,
                "d20": 3.8,
            }
        }
        cn = {
            "money_supply": {"latest_period": "2026-02", "prev_period": "2026-01", "m2_yoy": 8.1, "m1_yoy": 2.3},
            "credit": {"new_rmb_loan_100m": 1234},
            "inflation": {"cpi_yoy": 0.6, "ppi_yoy": -1.2},
            "policy_rates": {"lpr_1y": 3.35, "lpr_5y": 3.95},
            "interbank_rates": {"shibor_1w": 1.8},
            "fiscal_credit_impulse": {"fiscal_news_hits": 3},
        }
        return us, cn

    def test_build_data_integrity_has_header(self):
        us, cn = self.sample_us_cn()
        events = [{"source": "FRED:DGS10", "url": "u", "fetched_at": self.mod.now_utc_iso(), "status": "ok"}]
        out = self.mod.build_data_integrity(us, cn, events, self.mod.now_utc_iso())
        self.assertIn("report_period", out)
        self.assertIn("source_fetch", out)
        self.assertIn("field_calculation_notes", out)
        self.assertIn("missing_fields", out)
        self.assertIn("quality_gates", out)
        self.assertEqual(out["missing_fields"], [])
        self.assertFalse(out["quality_gates"]["has_missing_fields"])

    def test_missing_fields_detected(self):
        us, cn = self.sample_us_cn()
        cn["policy_rates"]["lpr_1y"] = None
        out = self.mod.build_data_integrity(us, cn, [], self.mod.now_utc_iso())
        self.assertIn("cn.policy_rates.lpr_1y", out["missing_fields"])
        self.assertTrue(out["quality_gates"]["has_missing_fields"])
        self.assertGreaterEqual(out["quality_gates"]["missing_fields_count"], 1)


if __name__ == "__main__":
    unittest.main()
