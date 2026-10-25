import json
import copy
import threading
import unittest
import urllib.request
import urllib.error
import time
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from app.server import Runtime, handler_for
from app.platform import Platform


class APITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runtime=Runtime()
        cls.server=ThreadingHTTPServer(("127.0.0.1",0),handler_for(cls.runtime))
        cls.url=f"http://127.0.0.1:{cls.server.server_port}"
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close()

    def test_state_and_static(self):
        for path in ("/", "/style.css", "/app.js", "/api/state", "/api/health"):
            with urllib.request.urlopen(self.url+path) as response:
                self.assertEqual(response.status,200)
                self.assertTrue(response.read())

    def test_mutation_and_exports(self):
        req=urllib.request.Request(self.url+"/api/command",data=json.dumps({"action":"fail","sensor":"ca"}).encode(),headers={"Content-Type":"application/json"})
        with urllib.request.urlopen(req) as r:
            self.assertTrue(json.load(r)["accepted"])
        with urllib.request.urlopen(self.url+"/api/state") as r:
            self.assertIsNone(json.load(r)["readings"]["ca"])
        for path in ("/api/export.json","/api/history.csv"):
            with urllib.request.urlopen(self.url+path) as r:
                self.assertIn("attachment",r.headers["Content-Disposition"])

    def test_cross_origin_and_invalid_input_rejected(self):
        for origin,payload,code in (("http://evil.invalid",b'{}',403),(None,b'[]',400)):
            headers={"Content-Type":"application/json"}
            if origin:headers["Origin"]=origin
            req=urllib.request.Request(self.url+"/api/command",data=payload,headers=headers)
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)
            self.assertEqual(ctx.exception.code,code)

    def test_platform_has_no_local_fallback(self):
        local=self.runtime.platform
        class BrokenPlatform:
            def read_snapshot(self):
                raise RuntimeError("not connected")
        try:
            self.runtime.platform=BrokenPlatform()
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(self.url+"/api/state")
            self.assertEqual(ctx.exception.code,503)
        finally:
            self.runtime.platform=local

    def test_stale_ditto_snapshot_rejected_even_when_simulator_is_available(self):
        local=self.runtime.platform
        p=Platform()
        stale={**self.runtime.twin.snapshot,"wall_time":time.time()-30}
        try:
            self.runtime.platform=p
            with patch.object(p,"request",return_value=stale):
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(self.url+"/api/state")
                self.assertEqual(ctx.exception.code,503)
        finally:
            self.runtime.platform=local

    def test_platform_response_comes_from_ditto_not_local_twin(self):
        local=self.runtime.platform
        p=Platform()
        platform_state={**self.runtime.twin.snapshot,"experiment_id":"platform-experiment","wall_time":time.time()}
        try:
            self.runtime.platform=p
            with patch.object(p,"request",return_value=platform_state):
                with urllib.request.urlopen(self.url+"/api/state") as response:
                    state=json.load(response)
                self.assertEqual(state["experiment_id"],"platform-experiment")
                self.assertEqual(state["connection"]["source"],"Ditto")
                self.assertNotEqual(self.runtime.twin.snapshot["experiment_id"],state["experiment_id"])
        finally:
            self.runtime.platform=local

    def test_export_and_replay_restore_experiment_without_executing_external_code(self):
        old=self.runtime.twin
        try:
            with urllib.request.urlopen(self.url+'/api/export.json') as response:
                saved=json.load(response)
            original_id=old.experiment_id
            request=urllib.request.Request(self.url+'/api/replay',data=json.dumps(saved).encode(),headers={'Content-Type':'application/json'})
            with urllib.request.urlopen(request) as response:self.assertTrue(json.load(response)['accepted'])
            self.assertEqual(self.runtime.twin.truth,saved['state']['truth'])
            self.assertNotEqual(original_id,self.runtime.twin.experiment_id)
            current=self.runtime.twin.experiment_id
            bad=copy.deepcopy(saved)
            bad['experiment']['timeline'].append({'kind':'command','data':{'action':'execute','value':'arbitrary'}})
            request=urllib.request.Request(self.url+'/api/replay',data=json.dumps(bad).encode(),headers={'Content-Type':'application/json'})
            with self.assertRaises(urllib.error.HTTPError) as context:urllib.request.urlopen(request)
            self.assertEqual(context.exception.code,400)
            self.assertEqual(self.runtime.twin.experiment_id,current)
        finally:self.runtime.twin=old
