import json
import time
import unittest
import urllib.error
from unittest.mock import Mock, patch

from app.model import Twin
from app.platform import Platform, ROOT, NAMESPACE, catalog, telemetry


class PlatformContractTests(unittest.TestCase):
    def snapshot(self):
        t = Twin()
        t.tick(10)
        return {**t.snapshot, "wall_time": time.time()}

    def test_every_measurement_has_existing_target_and_unit(self):
        objects = catalog()
        self.assertEqual(len(objects), 11)
        targets = {f"{NAMESPACE}:{name}" for name in objects}
        for name, attrs in objects.items():
            if attrs["kind"] == "sensor":
                self.assertIn(attrs["measures"], targets)
                self.assertIn(attrs["unit"], ("%", "m3/s"))
            if name != "site":
                self.assertEqual(attrs["_parents"], ROOT)

    def test_sample_id_shared_by_all_objects_and_root_published_last(self):
        snap = self.snapshot()
        values = telemetry(snap)
        self.assertEqual(set(values), set(catalog()))
        self.assertEqual(list(values)[-1], "site")
        for features in values.values():
            self.assertEqual(features["sample"]["revision"], snap["revision"])
            self.assertEqual(features["sample"]["experimentId"], snap["experiment_id"])
        self.assertEqual(values["site"]["snapshot"]["value"], snap)

    def test_publish_requires_broker_connection_and_all_receipts(self):
        platform = Platform()
        with self.assertRaises(RuntimeError):
            platform.publish(self.snapshot())
        receipt = Mock(rc=0)
        receipt.is_published.return_value = True
        platform.client = Mock()
        platform.client.publish.return_value = receipt
        platform.connected.set()
        platform.publish(self.snapshot())
        self.assertEqual(platform.client.publish.call_count, 11)
        for call in platform.client.publish.call_args_list:
            self.assertEqual(call.kwargs["qos"], 1)
            self.assertIn("topic", json.loads(call.args[1]))
        platform.last_publish = None
        receipt.is_published.return_value = False
        with self.assertRaises(RuntimeError):
            platform.publish(self.snapshot())
        self.assertIsNone(platform.last_publish)

    def test_snapshot_requires_platform_payload(self):
        p = Platform()
        with patch.object(p, "request", return_value={}):
            with self.assertRaises(RuntimeError):
                p.read_snapshot()
        snap = self.snapshot()
        with patch.object(p, "request", return_value=snap):
            self.assertEqual(p.read_snapshot(), snap)
            self.assertIsNotNone(p.last_read)

    def test_restart_changes_experiment_identity(self):
        t = Twin()
        old = t.snapshot["experiment_id"]
        t.tick(1)
        self.assertGreater(t.snapshot["revision"], 0)
        t.command({"action": "reset"})
        self.assertNotEqual(t.snapshot["experiment_id"], old)
        self.assertEqual(t.snapshot["revision"], 0)

    def test_provisioning_preserves_features_on_existing_objects(self):
        p = Platform()
        p.password = "test-only"
        with patch.object(p, "request", return_value={}) as request:
            with patch.dict("sys.modules", {"paho.mqtt.client": None}):
                with self.assertRaises(ImportError):
                    p.setup()
        writes = [c for c in request.call_args_list if len(c.args) == 3]
        self.assertEqual(len(writes), 11)
        self.assertTrue(all(c.args[0].endswith("/attributes") for c in writes))


if __name__ == "__main__":
    unittest.main()
