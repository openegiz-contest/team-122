import unittest
from app.reference import run
from app.model import Parameters,airflow,FAN_CURVE_K,FAN_SHUTOFF_PA


class ReferenceTests(unittest.TestCase):
    def test_published_network_reproduces_from_different_initial_guesses(self):
        a=run((200,50,200));b=run((400,100,400))
        self.assertLess(a['max_energy_residual_pa'],1e-6)
        self.assertLess(a['max_continuity_residual_m3s'],1e-9)
        self.assertLess(a['max_relative_flow_difference'],.011)
        for x,y in zip(a['branches'],b['branches']):
            self.assertAlmostEqual(x['computed_q'],y['computed_q'],places=6)

    def test_fan_operating_point_is_network_intersection(self):
        for resistance in (.65,1,2.5):
            f=airflow(Parameters(resistance_a=resistance))
            self.assertLess(f['fan_curve_residual_pa'],1e-8)
            self.assertAlmostEqual(f['pressure'],FAN_SHUTOFF_PA-FAN_CURVE_K*f['qt']**2)
        self.assertAlmostEqual(airflow(Parameters())['pressure'],600)
