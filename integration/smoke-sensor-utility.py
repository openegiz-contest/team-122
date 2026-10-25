"""Paired engineering demonstration through MQTT/Ditto, not independent field evidence."""
import hashlib,json,sys,time,urllib.request
from pathlib import Path
root=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(root))
from app.network_twin import NetworkTwin
from app.network import SENSORS,values

def read(path='/api/state'):
    with urllib.request.urlopen('http://127.0.0.1:8765'+path,timeout=10) as r:return json.load(r)

def send(data,path='/api/command'):
    req=urllib.request.Request('http://127.0.0.1:8765'+path,data=json.dumps(data).encode(),headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=60) as r:ack=json.load(r)
    for _ in range(60):
        s=read()
        if s['experiment_id']==ack['experiment_id'] and s['revision']>=ack['revision']:
            assert s['connection']['source']=='Ditto'
            return s
        time.sleep(.25)
    raise AssertionError('Receipt not propagated through Ditto')

t=NetworkTwin(20261026)
for c in ({'action':'pause'},{'action':'scenario','name':'blind_all'},{'action':'scenario','name':'gas'},
          {'action':'horizon','value':600},{'action':'speed','value':10}):t.command(c)
experiment=t.export_experiment()
spread={k:(max(values(h['c'],h['air'])[k] for h in t.observer.pool)-min(values(h['c'],h['air'])[k] for h in t.observer.pool))/SENSORS[k]['tolerance']/SENSORS[k]['cost'] for k in SENSORS}
choices={'proposed':t.snapshot['rankings'][0]['sensor'],'simple':max(SENSORS,key=lambda k:(spread[k],k)),
         'methane_priority':max(SENSORS,key=lambda k:(k.startswith('c'),spread[k],k))}
results={}
try:
    for policy,key in choices.items():
        before=send(experiment,'/api/replay')
        assert before['time']==0 and before['paused'] and before['truth']==t.snapshot['truth']
        assert before['width']==t.snapshot['width'] and len(before['objects'])==28
        assert all(o['spatial']['surveyed'] is False for o in before['objects'].values())
        assert all(abs(o['spatial']['length_error_m'])<1e-8 for o in before['objects'].values() if o['kind'] in ('airway','fan-airway'))
        assert before['rankings'][0]['sensor']==choices['proposed']
        send({'action':'restore','sensor':key});send({'action':'pause'})
        for _ in range(80):
            after=read()
            if after['last_decision'] and after['last_decision'].get('completed'):break
            time.sleep(.25)
        else:raise AssertionError('Repair did not finish')
        send({'action':'pause'})
        d=after['last_decision']
        assert d['completed_at']==SENSORS[key]['repair_s'] and d['target_time']==600
        assert d['actual_gain'] is not None
        # Compare live transported outcome with independently replayed local execution.
        expected=NetworkTwin.replay(experiment);expected.command({'action':'restore','sensor':key});expected.command({'action':'pause'})
        expected.tick(SENSORS[key]['repair_s'])
        assert abs(d['actual_gain']-expected.last_decision['actual_gain'])<1e-9
        results[policy]={'sensor':key,'source':after['connection']['source'],'experiment_id':before['experiment_id'],
                         'before_width':before['width'],'decision':d,'cost':SENSORS[key]['cost'],
                         'gain_per_cost':d['actual_gain']/SENSORS[key]['cost']}
    report=read('/api/utility');assert report['cases']==6048 and report['model_signature']==NetworkTwin.model_signature()
finally:send({'action':'reset'})
out={'passed':True,'checked_at_unix':time.time(),'model_signature':NetworkTwin.model_signature(),
     'scenario':'Nominal known initial gas; all channels lost; declared gas x2; horizon 600 s; same paused replay for each arm',
     'experiment':experiment,'experiment_sha256':hashlib.sha256(json.dumps(experiment,sort_keys=True).encode()).hexdigest(),
     'results':results,'spatial_objects_verified':28,'utility_report_cases':report['cases'],
     'limitation':'One engineering demonstration, not an independent validation or a representative estimate of policy superiority.'}
(root/'docs/live-sensor-comparison.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps(out['results'],ensure_ascii=False,indent=2))
print('PASS: matched replay, actual repair delays, spatial catalog and utility report through live platform')
