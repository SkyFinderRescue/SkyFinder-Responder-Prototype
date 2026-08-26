#!/usr/bin/env python3
import unittest

from engine import USCG_LEEWAY, simulate


class DriftEngineTests(unittest.TestCase):
    def test_current_only_moves_east(self):
        # Zero wind and an object whose intercept is zero isolate current motion.
        r = simulate(
            lat=34.25, lon=-119.84,
            current_u_mps=0.5, current_v_mps=0.0,
            wind_speed_kts=0.0, wind_from_deg=270.0,
            object_key="surfboard_person",
            hours=1.0, particles=500, seed=1,
        )
        self.assertGreater(r["estimate"]["center"]["lon"], -119.84)

    def test_direct_uscg_values_preserved(self):
        self.assertEqual(USCG_LEEWAY["sea_kayak_person"]["slope"], 0.011)
        self.assertEqual(USCG_LEEWAY["sea_kayak_person"]["intercept_kts"], 0.24)
        self.assertEqual(USCG_LEEWAY["sea_kayak_person"]["divergence_deg"], 15.0)
        self.assertEqual(USCG_LEEWAY["piw"]["std_error_kts"], 0.35)

    def test_sup_is_explicit_proxy(self):
        self.assertIn("proxy", USCG_LEEWAY["sup_person_proxy"]["source_match"])
        self.assertEqual(USCG_LEEWAY["sup_person_proxy"]["slope"], USCG_LEEWAY["surfboard_person"]["slope"])

    def test_probability_polygons_exist(self):
        r = simulate(
            lat=34.25, lon=-119.84,
            current_u_mps=0.1, current_v_mps=0.05,
            wind_speed_kts=12.0, wind_from_deg=270.0,
            object_key="sea_kayak_person",
            hours=2.0, particles=1000, seed=3,
        )
        self.assertGreaterEqual(len(r["estimate"]["probability_50_polygon"]), 4)
        self.assertGreaterEqual(len(r["estimate"]["probability_90_polygon"]), 4)
        self.assertFalse(r["operational_use"])


if __name__ == "__main__":
    unittest.main()
