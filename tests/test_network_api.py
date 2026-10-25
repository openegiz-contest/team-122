import json
import threading
import time
import unittest
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer
from app.server import Runtime, handler_for

class NetworkAPITests(unittest.TestCase):
    def setUp(self):
        self.runtime=Runtime(model='network');self.server=ThreadingHTTPServer(('127.0.0.1',0),handler_for(self.runtime))
        self.url='http://127.0.0.1:'+str(self.server.server_port)
        threading.Thread(target=self.server.serve_forever,daemon=True).start()
    def tearDown(self):self.server.shutdown();self.server.server_close()
    def get(self,path):
        with urllib.request.urlopen(self.url+path) as r:return r.read()
    def post(self,path,data):
        with urllib.request.urlopen(urllib.request.Request(self.url+path,data=json.dumps(data).encode(),headers={'Content-Type':'application/json'})) as r:return json.load(r)
    def test_network_page_and_api(self):
        self.assertIn(b'Gucheng',self.get('/'))
        s=json.loads(self.get('/api/state'));self.assertEqual(s['model'],'gucheng-network-v3')
        self.assertEqual(len(s['objects']),28)
    def test_replay_and_csv(self):
        self.post('/api/command',{'action':'scenario','name':'gas'});self.runtime.twin.tick(20)
        before=self.runtime.twin.snapshot['truth'];experiment=json.loads(self.get('/api/export.json'))
        self.post('/api/replay',experiment);self.assertEqual(before,self.runtime.twin.snapshot['truth'])
        self.assertIn(b'V7',self.get('/api/history.csv'))
    def test_invalid_parameter_transaction(self):
        before=dict(self.runtime.twin.params)
        with self.assertRaises(urllib.error.HTTPError) as caught:self.post('/api/command',{'action':'parameter','name':'fan_a','value':0})
        self.assertEqual(caught.exception.code,400);self.assertEqual(before,self.runtime.twin.params)
    def test_failed_solver_not_shown(self):
        self.runtime.simulation_error='Network did not converge'
        with self.assertRaises(urllib.error.HTTPError) as caught:self.get('/api/state')
        self.assertEqual(caught.exception.code,503)
    def test_command_receipt_identifies_result_and_reset(self):
        original=self.runtime.twin.experiment_id
        receipt=self.post('/api/command',{'action':'scenario','name':'closure'})
        self.assertEqual(receipt['experiment_id'],original)
        state=json.loads(self.get('/api/state'))
        self.assertEqual(receipt['revision'],state['revision'])
        self.assertTrue(state['params']['closed'])
        reset=self.post('/api/command',{'action':'reset'})
        self.assertNotEqual(reset['experiment_id'],original)
        self.assertEqual(reset['revision'],0)
    def test_platform_replay_receipt_does_not_bypass_ditto(self):
        from app.platform import Platform
        from unittest.mock import patch
        self.post('/api/command',{'action':'scenario','name':'gas'})
        self.runtime.twin.tick(20)
        expected=self.runtime.twin.snapshot['truth']
        experiment=self.runtime.twin.export_experiment()
        self.runtime.mode='platform';self.runtime.platform=Platform(model='network')
        self.runtime.simulation_error='old failure'
        receipt=self.post('/api/replay',experiment)
        self.assertEqual(expected,self.runtime.twin.snapshot['truth'])
        self.assertEqual(receipt['revision'],self.runtime.twin.revision)
        self.assertIsNone(self.runtime.simulation_error)
        with patch.object(self.runtime.platform,'read_snapshot',side_effect=RuntimeError('offline')):
            with self.assertRaises(urllib.error.HTTPError) as caught:self.get('/api/state')
            self.assertEqual(caught.exception.code,503)

if __name__=='__main__':unittest.main()
