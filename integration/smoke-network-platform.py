"""Live v3 acceptance. Resets demo before/after; reads every Thing from Ditto."""
import base64
import json
import os
import time
import urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
base=os.getenv('VENT_URL','http://127.0.0.1:8765')
def read():
    with urllib.request.urlopen(base+'/api/state',timeout=10) as r:return json.load(r)
def command(data):
    req=urllib.request.Request(base+'/api/command',data=json.dumps(data).encode(),headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=10) as r:assert r.status==200
def wait_state(predicate):
    for _ in range(60):
        try:
            s=read()
            assert s['connection']['source']=='Ditto' and s['model']=='gucheng-network-v3'
            assert time.time()-s['wall_time']<15
            if predicate(s):return s
        except (OSError,KeyError,ValueError):pass
        time.sleep(1)
    raise AssertionError('Fresh expected state not observed through Ditto')

platform=Path(os.getenv('OPENEGIZ_DIR',ROOT/'openegiz'));config={}
for line in (platform/'deploy/compose/.env').read_text(encoding='utf-8').splitlines():
    if line.strip() and not line.lstrip().startswith('#') and '=' in line:
        k,v=line.split('=',1);config[k]=v.strip().strip('"\'')
auth=base64.b64encode(('ditto:'+config['DITTO_PASSWORD']).encode()).decode()
def thing(name):
    req=urllib.request.Request('http://127.0.0.1:'+config.get('DITTO_PORT','8080')+'/api/2/things/org.openegiz.ventobserve:'+name,headers={'Authorization':'Basic '+auth})
    with urllib.request.urlopen(req,timeout=10) as r:return json.load(r)
def wait_thing(name,predicate):
    for _ in range(30):
        o=thing(name)
        if predicate(o):return o
        time.sleep(1)
    raise AssertionError('Expected Thing not observed: '+name)

checks=[]
first=wait_state(lambda s:True)
try:
    command({'action':'reset'});s=wait_state(lambda s:s['experiment_id']!=first['experiment_id'])
    command({'action':'pause'});s=wait_state(lambda s:s['paused'])
    for name in s['objects']:
        o=wait_thing(name,lambda o:o.get('features',{}).get('sample',{}).get('properties',{}).get('revision')==s['revision'] and o['features']['sample']['properties'].get('experimentId')==s['experiment_id'])
        assert o['attributes']['model']=='gucheng-network-v3'
        assert o['attributes']['kind']==s['objects'][name]['kind']
        if name!='site':assert o['features']['state']['properties']==s['objects'][name].get('state',{})
    assert len(s['objects'])==28
    checks.append('28 typed Things read directly from Ditto with matching experiment, revision, state')
    command({'action':'scenario','name':'resistance'})
    changed=wait_state(lambda s:s['params']['resistance_e6']==2)
    assert changed['air']['q']['e6']<s['air']['q']['e6']
    assert changed['air']['q']['e7']!=s['air']['q']['e7']
    wait_thing('e6',lambda o:o['features']['state']['properties']['resistance']==changed['air']['resistance']['e6'])
    checks.append('Resistance command propagated through MQTT, Ditto children and UI API')
    command({'action':'scenario','name':'closure'});closed=wait_state(lambda s:s['params']['closed'])
    assert abs(closed['air']['q']['e5'])<1e-8
    wait_thing('e5',lambda o:o['features']['state']['properties']['closed'])
    checks.append('Closed connection verified as zero-flow Thing')
    command({'action':'scenario','name':'blind_all'});blind=wait_state(lambda s:all(v is None for v in s['readings'].values()))
    command({'action':'scenario','name':'gas'});uncertain=wait_state(lambda s:s['params']['gas']==2 and bool(s['rankings']))
    key=uncertain['rankings'][0]['sensor'];command({'action':'restore','sensor':key})
    queued=wait_state(lambda s:s['sensors'][key]['repair_due'] is not None)
    command({'action':'speed','value':10});command({'action':'pause'})
    restored=wait_state(lambda s:s['sensors'][key]['usable'] and s['time']>=queued['sensors'][key]['repair_due'])
    wait_thing('sensor-'+key,lambda o:o['features']['state']['properties']['usable'])
    assert restored['last_decision']['completed']
    checks.append('Delayed repair completed and measurement returned through Ditto')
    command({'action':'scenario','name':'cancel'});wait_state(lambda s:not s['params']['closed'] and all(not v['failed'] for v in s['sensors'].values()))
    checks.append('Scenario cancellation observed through platform')
finally:command({'action':'reset'})
report={'passed':True,'checked_at_unix':time.time(),'model':'gucheng-network-v3','source':'live MQTT -> Ditto -> UI API','checks':checks}
(ROOT/'docs/platform-check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('PASS: live network acceptance; docs/platform-check.json')
