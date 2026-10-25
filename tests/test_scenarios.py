"""Acceptance checks for operator-visible consequences and cancellation."""
import unittest
from app.model import Twin, Parameters


class ScenarioTests(unittest.TestCase):
    def test_fan_reduces_flow_and_power_before_methane_rises(self):
        t = Twin()
        before = t.truth.copy()
        t.command({"action": "scenario", "name": "fan"})
        self.assertLess(t.truth["qt"], before["qt"])
        self.assertLess(t.truth["power_kw"], before["power_kw"])
        self.assertEqual(t.truth["ca"], before["ca"])
        t.tick(60)
        self.assertGreater(t.truth["ca"], before["ca"])
        self.assertGreater(t.truth["cb"], before["cb"])

    def test_resistance_propagates_to_other_branch(self):
        t = Twin()
        before = t.truth.copy()
        t.command({"action": "scenario", "name": "door"})
        self.assertLess(t.truth["qa"], before["qa"])
        self.assertGreater(t.truth["qb"], before["qb"])
        t.tick(60)
        self.assertGreater(t.truth["ca"], before["ca"])
        self.assertLess(t.truth["cb"], before["cb"])

    def test_gas_change_does_not_instantly_change_concentration_or_airflow(self):
        t = Twin()
        before = t.truth.copy()
        t.command({"action": "scenario", "name": "gas"})
        self.assertEqual(t.truth["qa"], before["qa"])
        self.assertEqual(t.truth["ca"], before["ca"])
        t.tick(60)
        self.assertGreater(t.truth["ca"], before["ca"])
        self.assertAlmostEqual(t.truth["cb"], before["cb"])

    def test_sensor_bias_scenario_can_be_cancelled(self):
        t = Twin()
        t.command({"action": "scenario", "name": "bias_ca"})
        self.assertAlmostEqual(t.snapshot["readings"]["ca"]-t.truth["ca"], .5)
        self.assertTrue(t.snapshot["conflict"])
        t.command({"action": "scenario", "name": "cancel"})
        self.assertFalse(t.snapshot["conflict"])
        self.assertEqual(t.bias["ca"], 0)
        self.assertEqual(t.params, Parameters())

    def test_cancel_recovers_gradually(self):
        t = Twin()
        base = t.truth["ca"]
        t.command({"action": "scenario", "name": "fan"})
        t.tick(120)
        high = t.truth["ca"]
        t.command({"action": "scenario", "name": "cancel"})
        self.assertEqual(t.truth["ca"], high)
        t.tick(30)
        self.assertLess(t.truth["ca"], high)
        self.assertGreater(t.truth["ca"], base)


if __name__ == "__main__":
    unittest.main()
