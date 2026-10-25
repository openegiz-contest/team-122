import copy
import random
import unittest
from app.model import Twin,SENSORS


class RobustnessTests(unittest.TestCase):
    def assert_covers(self,t):
        for key in ('ca','cb','cr','qa','qb','qt'):
            e=t.snapshot['estimate'][key]
            self.assertLessEqual(e['low']-1e-8,t.truth[key],key)
            self.assertGreaterEqual(e['high']+1e-8,t.truth[key],key)

    def test_bounded_noise_and_continuous_switching_inside_declared_limits(self):
        for seed in range(5):
            rng=random.Random(seed);t=Twin(seed=seed)
            t.command({'action':'scenario','name':'noise'})
            for step in range(36):
                if step%6==0:
                    for key,limits in [('resistance_a',(.7,2.4)),('resistance_b',(.7,2.4)),('gas_a',(.55,1.95)),('gas_b',(.55,1.95))]:
                        t.command({'action':'parameter','name':key,'value':rng.uniform(*limits)})
                if step==6:t.command({'action':'scenario','name':'blind_a'})
                if step==18:t.command({'action':'scenario','name':'blind_b'})
                t.tick(5)
                self.assertFalse(t.snapshot['conflict'],t.guard.faults)
                self.assert_covers(t)

    def test_lost_measurements_retain_last_information_and_then_widen(self):
        t=Twin();t.tick(120);width=t.snapshot['width'];truth=t.truth.copy()
        t.command({'action':'scenario','name':'blind_a'})
        self.assertAlmostEqual(t.snapshot['width'],width)
        self.assertEqual(t.truth,truth)
        t.tick(60)
        self.assertGreater(t.snapshot['width'],width)

    def test_delayed_and_frozen_values_are_not_current_observations(self):
        t=Twin();t.command({'action':'scenario','name':'delay_ca'})
        t.tick(20)
        self.assertIsNotNone(t.snapshot['readings']['ca'])
        self.assertGreater(t.snapshot['sensors']['ca']['age_s'],0)
        self.assertNotIn('ca',t.snapshot['quality']['used_channels'])
        t.command({'action':'restore','sensor':'ca'})
        t.command({'action':'scenario','name':'freeze_ca'});t.tick(5)
        self.assertFalse(t.snapshot['sensors']['ca']['usable'])
        self.assertEqual(t.snapshot['sensors']['ca']['quality'],'delayed')

    def test_polling_does_not_generate_new_noise(self):
        t=Twin(seed=42);t.command({'action':'scenario','name':'noise'});t.tick(5)
        a=copy.deepcopy(t.snapshot)
        for _ in range(10):
            b=t.observe()
            self.assertEqual(a['readings'],b['readings'])
            self.assertEqual(a['estimate'],b['estimate'])

    def test_disconnected_sensor_retains_last_received_value_and_time(self):
        t=Twin();t.tick(10);previous=t.snapshot['readings']['ca']
        t.command({'action':'fail','sensor':'ca'});t.command({'action':'scenario','name':'gas'});t.tick(30)
        self.assertIsNone(t.snapshot['readings']['ca'])
        self.assertEqual(t.snapshot['sensors']['ca']['last_value'],previous)
        self.assertEqual(t.snapshot['sensors']['ca']['age_s'],30)

    def test_bias_conflict_is_latched_and_explicit_repair_reinitializes(self):
        t=Twin();t.tick(120);t.command({'action':'bias','sensor':'ca','value':.5})
        self.assertTrue(t.snapshot['conflict'])
        self.assertFalse(t.snapshot['rankings'])
        t.tick(5);self.assertTrue(t.snapshot['conflict'])
        t.command({'action':'restore','sensor':'ca'})
        self.assertFalse(t.snapshot['conflict']);self.assert_covers(t)

    def test_outside_source_can_be_detected_with_measurements_but_not_without_them(self):
        t=Twin();t.command({'action':'scenario','name':'outside'})
        for _ in range(20):t.tick(10)
        self.assertTrue(t.snapshot['conflict'])
        t=Twin();t.command({'action':'scenario','name':'blind_all'});t.command({'action':'scenario','name':'outside'})
        for _ in range(60):t.tick(10)
        self.assertFalse(t.snapshot['conflict'])
        self.assertGreater(t.truth['ca'],t.snapshot['estimate']['ca']['high'])

    def test_experiment_replays_seed_errors_costs_and_commands(self):
        t=Twin(seed=16)
        for command in [{'action':'scenario','name':'noise'},{'action':'cost','sensor':'ca','value':7},
                        {'action':'scenario','name':'combined'},{'action':'sensor_config','sensor':'cb','settings':{'delay_s':10}}]:
            t.command(command);t.tick(10)
        t.command({'action':'checkpoint'});t.command({'action':'restore','sensor':'ca'})
        other=Twin.replay(t.export_experiment())
        for key in ('truth','readings','estimate','width','rankings','checkpoint','last_decision','sensors'):
            self.assertEqual(t.snapshot[key],other.snapshot[key],key)
        self.assertNotEqual(t.experiment_id,other.experiment_id)

    def test_invalid_settings_and_experiments_do_not_get_partially_applied(self):
        t=Twin();original=copy.deepcopy(t.measurements.config)
        with self.assertRaises(ValueError):t.command({'action':'sensor_config','sensor':'ca','settings':{'noise':.05,'unknown':4}})
        self.assertEqual(t.measurements.config,original)
        data=t.export_experiment();data['model_signature']='wrong'
        with self.assertRaises(ValueError):Twin.replay(data)
