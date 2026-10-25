"""Live acceptance check. Resets the demonstration experiment before and after."""
import json
import time
import urllib.request
import base64
import os
from pathlib import Path

base="http://127.0.0.1:8765"
def read():
    with urllib.request.urlopen(base+"/api/state",timeout=15) as r:
        return json.load(r)

for attempt in range(60):
    try:
        first=read()
        break
    except Exception:
        if attempt==59:
            raise
        time.sleep(1)
assert first["connection"]["source"]=="Ditto", "must be platform mode"
def command(data):
    req=urllib.request.Request(base+"/api/command",data=json.dumps(data).encode(),headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(req,timeout=10) as response:
        assert response.status==200

def wait_state(predicate):
    for _ in range(40):
        state=read()
        assert state["connection"]["source"]=="Ditto"
        assert time.time()-state["wall_time"]<15, "stale platform state"
        if predicate(state):return state
        time.sleep(1)
    raise AssertionError("Expected platform state not observed")

config={}
platform=Path(os.getenv("OPENEGIZ_DIR",Path(__file__).resolve().parent.parent/"openegiz"))
for line in (platform/"deploy/compose/.env").read_text(encoding="utf-8").splitlines():
    if line.strip() and not line.lstrip().startswith("#") and "=" in line:
        key,value=line.split("=",1);config[key]=value.strip().strip("\"'")
auth=base64.b64encode(("ditto:"+config["DITTO_PASSWORD"]).encode()).decode()
def thing(name):
    req=urllib.request.Request("http://127.0.0.1:"+config.get("DITTO_PORT","8080")+"/api/2/things/org.openegiz.ventobserve:"+name,
                               headers={"Authorization":"Basic "+auth})
    with urllib.request.urlopen(req,timeout=10) as response:return json.load(response)

def wait_thing(name,predicate):
    for _ in range(20):
        obj=thing(name)
        if predicate(obj):return obj
        time.sleep(1)
    raise AssertionError("Expected Thing state not observed: "+name)

checks=[]
try:
    command({"action":"reset"})
    initial=wait_state(lambda s:s["experiment_id"]!=first["experiment_id"])
    command({"action":"pause"})
    initial=wait_state(lambda s:s["paused"])
    for name in ("site","fan","face-a","face-b","return","regulator","sensor-qa","sensor-qb","sensor-ca","sensor-cb","sensor-qt"):
        obj=wait_thing(name,lambda o:o.get("features",{}).get("sample",{}).get("properties",{}).get("simulationTime")==initial["time"]
                       and o["features"]["sample"]["properties"].get("experimentId")==initial["experiment_id"])
        assert obj["attributes"]["kind"]!="ventilation", "untyped Thing"
        sample=obj["features"]["sample"]["properties"]
        assert sample["experimentId"]==initial["experiment_id"], "old experiment"
        assert sample["simulationTime"]==initial["time"], "inconsistent model time"
    checks.append("11 typed Things read directly from Ditto with matching experiment/time")
    command({"action":"scenario","name":"blind_a"})
    blind=wait_state(lambda s:s["readings"]["ca"] is None and s["readings"]["qa"] is None)
    assert blind["width"]>=initial["width"] and blind["rankings"]
    wait_thing("sensor-ca",lambda o:o["features"]["available"]["properties"]["value"] is False)
    chosen=blind["rankings"][0]["sensor"]
    command({"action":"restore","sensor":chosen})
    restored=wait_state(lambda s:s["readings"][chosen] is not None)
    assert restored["width"]<=blind["width"]+1e-10
    checks.append("Sensor loss and restoration change uncertainty through platform")
    command({"action":"scenario","name":"fan"})
    reduced=wait_state(lambda s:s["params"]["fan"]==.65)
    assert reduced["truth"]["qt"]<initial["truth"]["qt"]
    assert reduced["truth"]["power_kw"]<initial["truth"]["power_kw"]
    wait_thing("fan",lambda o:o["features"]["speed"]["properties"]["value"]==.65)
    command({"action":"speed","value":10})
    command({"action":"pause"})
    wait_state(lambda s:s["time"]>=reduced["time"]+30 and s["truth"]["ca"]>initial["truth"]["ca"])
    checks.append("Fan change reduces flow/power and methane increases dynamically")
    command({"action":"scenario","name":"cancel"})
    wait_state(lambda s:s["params"]["fan"]==1 and all(not x["failed"] for x in s["sensors"].values()))
    checks.append("Cancellation restored parameters and sensors")
finally:
    command({"action":"reset"})
report=Path(__file__).resolve().parent.parent/"docs/platform-check.json"
report.write_text(json.dumps({"passed":True,"checked_at_unix":time.time(),"checks":checks,
                              "source":"live MQTT -> Ditto -> UI API"},indent=2),encoding="utf-8")
print("PASS: live platform acceptance; report:",report)
