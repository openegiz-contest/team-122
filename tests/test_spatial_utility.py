import math,unittest
from app.network import catalog,solve,steady,advance,SENSORS
from app.network_observer import Observer
from app.sensor_utility import outcome

class SpatialTests(unittest.TestCase):
    def test_metric_lengths_and_shared_endpoints(self):
        objects=catalog()
        for obj in objects.values():
            if obj['kind'] not in ('airway','fan-airway'):continue
            a,b=obj['spatial']['centerline_m']
            self.assertEqual(a,objects[obj['from']]['spatial']['xyz_m'])
            self.assertEqual(b,objects[obj['to']]['spatial']['xyz_m'])
            self.assertAlmostEqual(math.dist(a,b),obj['length'],places=8)
            self.assertAlmostEqual(obj['spatial']['square_section_side_m']**2,obj['area'])
            self.assertAlmostEqual(obj['spatial']['volume_m3'],obj['length']*obj['area'])
    def test_sensor_positions_and_provenance(self):
        objects=catalog();self.assertFalse(objects['site']['spatial']['surveyed'])
        for obj in objects.values():
            self.assertFalse(obj['spatial']['surveyed'])
            if obj['kind']=='sensor':
                target=objects[obj['target']]['spatial']
                expected=target.get('xyz_m') or [(a+b)/2 for a,b in zip(*target['centerline_m'])]
                self.assertEqual(obj['spatial']['xyz_m'],expected)

class UtilityTests(unittest.TestCase):
    def test_impossible_repaired_reading_is_not_zero_uncertainty(self):
        o=Observer();future=o.forecast(60);truth=advance(steady(solve()),solve(),1,60)[0]
        from app.network_observer import width
        base=width(future);result=outcome(o.pool,future,truth,1000,'c_V7',base)
        self.assertEqual(result['conflict'],1)
        self.assertEqual(result['gain_per_cost'],0)
        self.assertEqual(result['remaining_width'],base)
        self.assertEqual(result['contains_truth'],0)
    def test_bounded_noise_keeps_true_candidate(self):
        o=Observer();future=o.forecast(120);a=solve();c=steady(a)
        from app.network_observer import width
        for sign in (-1,0,1):
            for key in ('q_e6','c_V7'):
                from app.network import values
                v=values(c,a)[key]+sign*SENSORS[key]['tolerance']
                result=outcome(o.pool,future,c,v,key,width(future))
                self.assertEqual(result['contains_truth'],1)
                self.assertEqual(result['conflict'],0)

if __name__=='__main__':unittest.main()
