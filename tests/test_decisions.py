import unittest
from app.model import Twin


class DecisionTests(unittest.TestCase):
    def make_twin(self):
        t=Twin(seed=9);t.command({'action':'scenario','name':'noise'});t.tick(120)
        t.command({'action':'fail','sensor':'ca'});t.command({'action':'fail','sensor':'cb'});t.tick(60)
        return t

    def test_repair_only_samples_selected_channel(self):
        t=self.make_twin();old=t.snapshot['readings'].copy()
        t.command({'action':'restore','sensor':'ca'})
        for key in ('qa','qb','qt','cb'):self.assertEqual(old[key],t.snapshot['readings'][key])

    def test_cost_changes_ranking_without_changing_physics_or_readings(self):
        t=self.make_twin();truth=t.truth.copy();readings=t.snapshot['readings'].copy()
        t.command({'action':'cost','sensor':'ca','value':100})
        self.assertEqual(t.snapshot['rankings'][0]['sensor'],'cb')
        t.command({'action':'cost','sensor':'ca','value':.1})
        self.assertEqual(t.snapshot['rankings'][0]['sensor'],'ca')
        self.assertEqual(t.truth,truth);self.assertEqual(t.snapshot['readings'],readings)

    def test_checkpoint_and_actual_gain_are_server_state(self):
        t=self.make_twin();t.command({'action':'checkpoint'})
        before=t.snapshot['width'];t.command({'action':'restore','sensor':'ca'})
        d=t.snapshot['last_decision']
        self.assertAlmostEqual(d['actual_gain'],before-t.snapshot['width'])
        self.assertEqual(t.snapshot['checkpoint']['width'],before)
        self.assertIsNotNone(d['expected_gain'])

    def test_flow_repair_has_zero_immediate_methane_gain_in_this_observer(self):
        t=Twin();t.tick(60);t.command({'action':'fail','sensor':'qa'})
        self.assertEqual(t.snapshot['rankings'][0]['gain'],0)
