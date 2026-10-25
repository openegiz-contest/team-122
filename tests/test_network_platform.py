import time
import unittest
from unittest.mock import patch
from app.network_twin import NetworkTwin
from app.platform import catalog,telemetry,Platform,NAMESPACE

class NetworkPlatformTests(unittest.TestCase):
    def test_catalog_and_snapshots_share_ids(self):
        t=NetworkTwin();snap={**t.snapshot,'wall_time':time.time()};cat=catalog('network');data=telemetry(snap)
        self.assertEqual(len(cat),28);self.assertEqual(set(cat),set(data));self.assertEqual(set(cat),set(snap['objects']))
        self.assertEqual(list(data)[-1],'site')
        for name,features in data.items():
            self.assertEqual(features['sample']['experimentId'],snap['experiment_id'])
            self.assertEqual(features['sample']['revision'],snap['revision'])
            for link in cat[name].get('links',[]):self.assertIn(link.split(':')[1],cat)
    def test_child_changes_and_new_model_guard(self):
        t=NetworkTwin();before=telemetry({**t.snapshot,'wall_time':time.time()})
        t.command({'action':'scenario','name':'resistance'})
        after=telemetry({**t.snapshot,'wall_time':time.time()})
        for key in ('e6','e5','e7'):self.assertNotEqual(before[key]['state'],after[key]['state'])
        p=Platform(model='network')
        with patch.object(p,'request',return_value={'estimate':{}}):
            with self.assertRaises(RuntimeError):p.read_snapshot()
        with patch.object(p,'request',return_value=t.snapshot):self.assertEqual(p.read_snapshot(),t.snapshot)

if __name__=='__main__':unittest.main()
