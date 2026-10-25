import copy
import unittest
from app.network import *
from app.reference import run
from app.network_twin import NetworkTwin, SCENARIOS
from app.network_observer import Observer

class NetworkPhysicsTests(unittest.TestCase):
    def test_reference_and_balances(self):
        a=solve()
        for e in run()['branches']:self.assertAlmostEqual(a['q'][e['branch']],e['computed_q'],places=6)
        self.assertLess(a['energy_residual_pa'],1e-6)
        self.assertLess(a['continuity_residual_m3s'],1e-9)
    def test_closed_and_reverse(self):
        a=solve({'closed':True});self.assertAlmostEqual(a['q']['e5'],0,places=9)
        b=solve({'fan_a':1.2,'fan_b':.5});self.assertLess(b['q']['e5'],0)
        c=steady(b);n,ledger=advance(c,b,1,600)
        self.assertLess(abs(ledger['mass_residual_m3']),1e-8)
        for key in c:self.assertAlmostEqual(c[key],n[key],places=12)
    def test_neighbour_response(self):
        a=solve();b=solve({'resistance_e6':2})
        self.assertLess(b['q']['e6'],a['q']['e6'])
        self.assertGreater(abs(b['q']['e7']-a['q']['e7']),1)
    def test_conservation_and_timestep(self):
        a=solve();c=steady(a)
        one,l=advance(c,a,2,600,max_step=1)
        five,_=advance(c,a,2,600,max_step=5)
        half,_=advance(c,a,2,600,max_step=.5)
        self.assertLess(abs(l['mass_residual_m3']),1e-8)
        self.assertLess(max(abs(five[n]-half[n])*100 for n in c),.002)
        self.assertLess(max(abs(one[n]-half[n]) for n in c),max(abs(five[n]-half[n]) for n in c))
        self.assertGreater(one['V9'],c['V9'])
    def test_reject_unsupported(self):
        for p in ({'fan_a':0},{'gas':float('nan')},{'closed':1},{'foo':1}):
            with self.assertRaises(ValueError):solve(p)
    def test_catalog_relationships(self):
        cat=catalog()
        for obj in cat.values():
            for link in obj.get('links',[]):self.assertIn(link,cat)
        self.assertEqual(len([v for v in cat.values() if v['kind'] in ('airway','fan-airway')]),9)

class NetworkTwinTests(unittest.TestCase):
    def test_scenarios_and_replay(self):
        for name in SCENARIOS:
            with self.subTest(name=name):
                t=NetworkTwin();t.command({'action':'scenario','name':name});t.tick(30)
                r=NetworkTwin.replay(t.export_experiment())
                for key in ('air','truth','estimate','readings','forecast','conflict'):self.assertEqual(t.snapshot[key],r.snapshot[key])
    def test_stale_and_freeze(self):
        for name in ('freeze','delay'):
            t=NetworkTwin();t.command({'action':'scenario','name':name});t.tick(20)
            self.assertFalse(t.snapshot['sensors']['c_V7']['usable'])
            self.assertNotIn('c_V7',t.snapshot['quality']['used_channels'])
    def test_repair_takes_time(self):
        t=NetworkTwin();t.command({'action':'fail','sensor':'q_e6'});t.command({'action':'restore','sensor':'q_e6'})
        t.tick(5);self.assertIn('q_e6',t.failed)
        t.tick(5);self.assertNotIn('q_e6',t.failed)
        self.assertTrue(t.snapshot['sensors']['q_e6']['usable'])
    def test_repair_inside_large_step_and_history_retention(self):
        t=NetworkTwin();before=copy.deepcopy(t.snapshot['estimate'])
        t.command({'action':'scenario','name':'blind_all'});self.assertEqual(before,t.snapshot['estimate'])
        t.command({'action':'scenario','name':'gas'});t.command({'action':'restore','sensor':'q_e6'});t.tick(40)
        self.assertEqual(t.last_decision['completed_at'],10)
        self.assertIn({'time':10.,'text':'Восстановлен q_e6'},t.events)
        self.assertIsNotNone(t.last_decision['actual_gain'])
    def test_no_truth_input(self):
        a=NetworkTwin();b=NetworkTwin()
        for t in (a,b):t.command({'action':'scenario','name':'blind_all'})
        b.params['gas']=3
        a.tick(60);b.tick(60)
        self.assertNotEqual(a.gas,b.gas)
        self.assertEqual(a.snapshot['estimate'],b.snapshot['estimate'])
        self.assertEqual(a.snapshot['rankings'],b.snapshot['rankings'])
    def test_conflict_suppresses_recommendation(self):
        t=NetworkTwin();t.command({'action':'scenario','name':'bias'})
        self.assertTrue(t.snapshot['conflict']);self.assertFalse(t.snapshot['rankings']);self.assertIsNone(t.snapshot['width'])
    def test_cancel_is_dynamic(self):
        t=NetworkTwin();t.command({'action':'scenario','name':'gas'});t.tick(600);before=dict(t.gas)
        t.command({'action':'scenario','name':'cancel'});self.assertEqual(before,t.gas)
        t.tick(600);self.assertLess(t.gas['V7'],before['V7'])
    def test_signature_rejects_old(self):
        with self.assertRaises(ValueError):NetworkTwin.replay({'schema_version':2})

if __name__=='__main__':unittest.main()
