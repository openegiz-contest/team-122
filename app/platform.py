"""OpenEgiz adapter: provisioning via HTTP, telemetry via MQTT, UI via Ditto.

Contract checked against OpenEgiz 8d60b6dffdfd153e7257ecf5921327920aaba03f.
No simulation-to-HTTP fallback in platform mode.
"""
import os
import json
import base64
import time
import threading

from .model import SENSORS
import urllib.request
import urllib.error

NAMESPACE = "org.openegiz.ventobserve"
ROOT = f"{NAMESPACE}:site"


def catalog(model='legacy'):
    """Typed objects and explicit physical/measurement relationships (11 Things)."""
    if model=='network':
        from .network import catalog as network_catalog
        objects=network_catalog()
        for name,attrs in objects.items():
            attrs.update({'_isType':False,'model':'gucheng-network-v3'})
            attrs['links']=[f'{NAMESPACE}:{link}' for link in attrs.get('links',[])]
            if name!='site':attrs['_parents']=ROOT
            if attrs['kind']=='sensor':attrs['measures']=f"{NAMESPACE}:{attrs['target']}"
        return objects
    def ref(name):
        return f"{NAMESPACE}:{name}"
    objects = {
        "site": {"name": "Участок VentObserve", "kind": "ventilation-site",
                 "topology": {"inlet": "intake", "outlet": "return", "branches": [
                     {"id": "a", "from": "split", "to": "merge", "thingId": ref("face-a")},
                     {"id": "b", "from": "split", "to": "merge", "thingId": ref("face-b")},
                     {"id": "bypass", "from": "split", "to": "merge", "baseResistance": .8}],
                     "commonResistance": .035, "resistanceUnit": "Pa*s2/m6"}},
        "fan": {"name": "Вентилятор", "kind": "fan", "supplies": ref("site"),
                "pressureCoefficientPa": 600, "efficiency": .72},
        "face-a": {"name": "Участок A", "kind": "working-zone", "volumeM3": 1800,
                   "baseResistance": .10, "baseGasSourceM3s": .35,
                   "receivesAirFrom": ref("fan"), "dischargesTo": ref("return")},
        "face-b": {"name": "Участок B", "kind": "working-zone", "volumeM3": 2400,
                   "baseResistance": .14, "baseGasSourceM3s": .22,
                   "receivesAirFrom": ref("fan"), "dischargesTo": ref("return")},
        "return": {"name": "Возвратная выработка", "kind": "mixing-junction",
                   "receivesFrom": [ref("face-a"), ref("face-b"), "bypass"]},
        "regulator": {"name": "Сопротивление ветви A", "kind": "branch-regulator",
                      "controls": ref("face-a")},
    }
    for key, sensor in SENSORS.items():
        target = "site" if key == "qt" else "face-"+key[-1]
        objects["sensor-"+key] = {
            "name": sensor["name"], "kind": "sensor", "measures": ref(target),
            "quantity": "methane" if key.startswith("c") else "airflow",
            "unit": "%" if key.startswith("c") else "m3/s",
            "tolerance": sensor["tolerance"], "abstractRestorationCost": sensor["cost"]}
    for name, attrs in objects.items():
        attrs.update({"_isType": False, "model": "synthetic research prototype"})
        if name != "site":
            attrs["_parents"] = ROOT
    return objects


def telemetry(snapshot):
    """Child updates precede the root snapshot; sample IDs expose mixed revisions.

    MQTT acknowledgements are broker receipts, not atomic Ditto transactions.
    """
    if snapshot.get('model')=='gucheng-network-v3':
        features={name:{'state':obj.get('state',{})} for name,obj in snapshot['objects'].items() if name!='site'}
        for name,vals in features.items():
            state=vals['state']
            if 'flow_m3_s' in state:vals['airflow']={'value':state['flow_m3_s'],'unit':'m3/s'}
            if 'methane_pct' in state:vals['methane']={'value':state['methane_pct'],'unit':'%'}
            if 'head_pa' in state:vals['head']={'value':state['head_pa'],'unit':'Pa'}
        features['site']={'snapshot':{'value':snapshot},'time':{'value':snapshot['time'],'unit':'s'},
                          'uncertainty':{'value':snapshot['width'],'unit':'percentage points'}}
        for vals in features.values():
            vals['sample']={'experimentId':snapshot['experiment_id'],'revision':snapshot['revision'],
                            'simulationTime':snapshot['time'],'wallTime':snapshot['wall_time']}
        return features
    p, truth = snapshot["params"], snapshot["truth"]
    features = {
        "fan": {"speed": {"value": p["fan"]}, "pressure": {"value": truth["pressure"], "unit": "Pa"},
                "power": {"value": truth["power_kw"], "unit": "kW"}},
        "regulator": {"resistance_factor": {"value": p["resistance_a"]}},
    }
    for name, q, c in (("face-a", "qa", "ca"), ("face-b", "qb", "cb"), ("return", "qt", "cr")):
        features[name] = {"airflow": {"value": truth[q], "unit": "m3/s"},
                          "methane": {"value": truth[c], "unit": "%"}}
        if name != "return":
            suffix = name[-1]
            features[name].update({"gas_source": {"value": (.35 if suffix == "a" else .22)*p["gas_"+suffix], "unit": "m3/s"},
                                   "resistance": {"value": (.10 if suffix == "a" else .14)*p["resistance_"+suffix], "unit": "Pa*s2/m6"},
                                   "estimate": snapshot["estimate"][c], "risk": {"value": snapshot["risk"][c]}})
    for key, val in snapshot["readings"].items():
        features["sensor-"+key] = {"reading": {"value": val, "unit": "%" if key.startswith("c") else "m3/s"},
                                    "available": {"value": not snapshot["sensors"][key]["failed"]}}
    features["site"] = {"snapshot": {"value": snapshot},
                        "time": {"value": snapshot["time"], "unit": "s"},
                        "uncertainty": {"value": snapshot["width"], "unit": "percentage points"},
                        "bypass": {"airflow": truth["ql"], "conductanceFactor": p["leakage"], "unit": "m3/s"},
                        "observer": {"compatible": snapshot["candidate_count"], "conflict": snapshot["conflict"]}}
    for vals in features.values():
        vals["sample"] = {"experimentId": snapshot["experiment_id"], "revision": snapshot["revision"],
                          "simulationTime": snapshot["time"], "wallTime": snapshot["wall_time"]}
    return features


def protocol(name, features):
    return {"topic": f"{NAMESPACE}/{name}/things/twin/commands/modify",
            "headers": {"response-required": False}, "path": "/features",
            "value": {k: {"properties": v} for k, v in features.items()}}


class Platform:
    def __init__(self,model='legacy'):
        self.model=model
        self.url = os.getenv("DITTO_URL", "http://localhost:8080").rstrip("/")
        self.password = os.getenv("DITTO_PASSWORD", "")
        self.status = "connecting"
        self.last_publish = None
        self.last_error = None
        self.last_read = None
        self.client = None
        self.connected = threading.Event()

    def request(self, path, data=None, method="GET"):
        auth = base64.b64encode((os.getenv("DITTO_USER", "ditto")+":"+self.password).encode()).decode()
        req = urllib.request.Request(self.url+path, data=None if data is None else json.dumps(data).encode(),
                                     method=method, headers={"Authorization": "Basic "+auth,
                                                             "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=4) as r:
            raw = r.read()
            return json.loads(raw) if raw else {}

    def setup(self):
        if not self.password:
            raise RuntimeError("DITTO_PASSWORD не задан")
        for name, attrs in catalog(self.model).items():
            # Create only if absent; do not erase existing state at restart.
            try:
                self.request(f"/api/2/things/{NAMESPACE}:{name}")
                # Upgrade descriptive attributes without erasing live features.
                self.request(f"/api/2/things/{NAMESPACE}:{name}/attributes", attrs, "PUT")
            except urllib.error.HTTPError as e:
                if e.code != 404:
                    raise
                self.request(f"/api/2/things/{NAMESPACE}:{name}",
                             {"policyId": "default:basic_policy", "attributes": attrs, "features": {}}, "PUT")
        import paho.mqtt.client as mqtt
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="ventobserve")
        self.connected.clear()
        def on_connect(_client, _userdata, _flags, reason_code, _properties):
            if reason_code == 0:
                self.connected.set()
                self.status = "connected"
            else:
                self.connected.clear()
                self.status = "error"
        def on_disconnect(_client, _userdata, _flags, _reason_code, _properties):
            self.connected.clear()
            self.status = "disconnected"
        client.on_connect, client.on_disconnect = on_connect, on_disconnect
        client.reconnect_delay_set(min_delay=1, max_delay=10)
        try:
            client.connect(os.getenv("MQTT_HOST", "localhost"), int(os.getenv("MQTT_PORT", "1883")), 30)
            client.loop_start()
            if not self.connected.wait(timeout=10):
                raise RuntimeError("MQTT connection was not acknowledged")
            self.client = client
        except Exception:
            client.disconnect()
            client.loop_stop()
            raise
        self.status = "connected"

    def publish(self, snapshot):
        if not self.client or not self.connected.is_set():
            raise RuntimeError("MQTT disconnected")
        for name, vals in telemetry(snapshot).items():
            result = self.client.publish("telemetry/ventobserve-"+name, json.dumps(protocol(name, vals), allow_nan=False), qos=1)
            result.wait_for_publish(timeout=3)
            if result.rc != 0 or not result.is_published():
                raise RuntimeError("MQTT publish failed")
        self.last_publish = time.time()
        self.status = "published"
        self.last_error = None

    def read_snapshot(self):
        body = self.request(f"/api/2/things/{ROOT}/features/snapshot/properties/value")
        if not isinstance(body, dict) or "estimate" not in body:
            raise RuntimeError("Ожидание снимка в Ditto")
        if self.model=='network' and body.get('model')!='gucheng-network-v3':
            raise RuntimeError('Ditto contains a different model version')
        self.last_read = time.time()
        return body

    def close(self):
        if self.client:
            self.client.disconnect()
            self.client.loop_stop()
            self.client = None
        self.connected.clear()
