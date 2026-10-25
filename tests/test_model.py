import math
import unittest
from app.model import Twin, Parameters, airflow, gas_step, advance, risk_interval
from app.platform import protocol, NAMESPACE


class PhysicsTests(unittest.TestCase):
    def test_node_continuity_and_pressure_balance(self):
        for fan in (.2, .65, 1, 1.2):
            p = Parameters(fan=fan, resistance_a=2.5)
            f = airflow(p)
            self.assertAlmostEqual(f["qt"], f["qa"]+f["qb"]+f["ql"], places=10)
            self.assertAlmostEqual(.10*p.resistance_a*f["qa"]**2, f["parallel_dp"], places=10)
            self.assertAlmostEqual(.035*f["qt"]**2+f["parallel_dp"], f["pressure"], places=9)

    def test_fan_similarity_and_energy(self):
        a, b = airflow(Parameters()), airflow(Parameters(fan=.5))
        self.assertAlmostEqual(b["qt"]/a["qt"], .5)
        self.assertAlmostEqual(b["power_kw"]/a["power_kw"], .125)

    def test_damper_has_network_consequences(self):
        a = airflow(Parameters())
        b = airflow(Parameters(resistance_a=2.5))
        self.assertLess(b["qa"], a["qa"])
        self.assertGreater(b["qb"], a["qb"])

    def test_gas_balance_exact_and_step_invariant(self):
        c = gas_step(.2, 30, .3, 1800, 120)
        d = .2
        for _ in range(12):
            d = gas_step(d, 30, .3, 1800, 10)
        self.assertAlmostEqual(c, d)
        equilibrium = 100*.3/30.3
        self.assertAlmostEqual(gas_step(equilibrium,30,.3,1800,99), equilibrium)

    def test_no_ventilation_accumulates_gas(self):
        self.assertGreater(gas_step(.2,0,.3,1800,60), .2)

    def test_return_methane_flux(self):
        p = Parameters()
        f = advance([.4,.6],p,0)
        self.assertAlmostEqual(f["cr"]*(f["qt"]+.35+.22), (f["qa"]+.35)*.4+(f["qb"]+.22)*.6)


class ObservationTests(unittest.TestCase):
    def make_twin(self):
        t = Twin()
        for _ in range(6):
            t.tick(20)
        return t

    def test_true_base_scenario_is_compatible(self):
        t = self.make_twin()
        self.assertFalse(t.snapshot["conflict"])
        for key in ("ca","cb"):
            e = t.snapshot["estimate"][key]
            self.assertLessEqual(e["low"], t.truth[key])
            self.assertGreaterEqual(e["high"], t.truth[key])

    def test_lost_measurements_expand_scenario_set(self):
        t = self.make_twin()
        n, width = t.snapshot["candidate_count"], t.snapshot["width"]
        t.command({"action":"scenario","name":"blind_all"})
        self.assertEqual(t.snapshot["candidate_count"],256)
        self.assertAlmostEqual(t.snapshot["width"],width)
        t.tick(120)
        self.assertGreater(t.snapshot["width"],width)
        self.assertGreater(t.snapshot["candidate_count"],n)

    def test_restore_narrows_and_ranking_nonnegative(self):
        t = self.make_twin()
        t.command({"action":"scenario","name":"blind_a"})
        width = t.snapshot["width"]
        ranks = t.snapshot["rankings"]
        self.assertTrue(ranks)
        self.assertTrue(all(r["gain"]>=0 for r in ranks))
        t.command({"action":"restore","sensor":ranks[0]["sensor"]})
        self.assertLessEqual(t.snapshot["width"],width)

    def test_observer_not_using_hidden_source_as_input(self):
        a,b = self.make_twin(),self.make_twin()
        for t in (a,b):
            t.command({"action":"scenario","name":"blind_all"})
        b.command({"action":"scenario","name":"gas"})
        a.tick(10);b.tick(10)
        self.assertNotEqual(a.truth["ca"],b.truth["ca"])
        self.assertEqual(a.snapshot["estimate"],b.snapshot["estimate"])
        self.assertEqual(a.snapshot["rankings"],b.snapshot["rankings"])

    def test_bias_is_detected_as_model_conflict(self):
        t = self.make_twin()
        t.command({"action":"bias","sensor":"ca","value":10})
        t.command({"action":"fail","sensor":"qb"})
        self.assertTrue(t.snapshot["conflict"])
        self.assertEqual(t.snapshot["candidate_count"],0)
        self.assertEqual(t.snapshot["rankings"],[])

    def test_cancel_and_reset_have_different_gas_effects(self):
        t = self.make_twin()
        t.command({"action":"scenario","name":"fan"});t.tick(60)
        old = t.gas[:]
        t.command({"action":"scenario","name":"cancel"})
        self.assertEqual(t.gas,old)
        self.assertEqual(t.params,Parameters())
        t.command({"action":"reset"})
        self.assertEqual(t.time,0)
        self.assertFalse(t.failed)

    def test_invalid_commands_rejected(self):
        t = Twin()
        for c in ({"action":"parameter","name":"gas_a","value":10},
                  {"action":"speed","value":100}, {"action":"fail","sensor":"unknown"},
                  {"action":"parameter","name":"fan","value":float("nan")}):
            with self.assertRaises(ValueError):
                t.command(c)

    def test_risk_intervals(self):
        self.assertEqual(risk_interval(.2,.7),"below")
        self.assertEqual(risk_interval(.7,1.2),"uncertain")
        self.assertEqual(risk_interval(1.1,1.3),"exceedance")

    def test_pause(self):
        t = self.make_twin()
        time,gas = t.time,t.gas[:]
        t.command({"action":"pause"});t.tick(10)
        self.assertEqual(t.time,time)
        self.assertEqual(t.gas,gas)

    def test_ditto_contract(self):
        m = protocol("face-a",{"airflow":{"value":25,"unit":"m3/s"}})
        self.assertEqual(m["topic"],NAMESPACE+"/face-a/things/twin/commands/modify")
        self.assertEqual(m["path"],"/features")
        self.assertEqual(m["value"]["airflow"]["properties"]["value"],25)


if __name__ == "__main__":
    unittest.main()
