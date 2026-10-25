import json,time,urllib.request
from pathlib import Path
root=Path(__file__).resolve().parent.parent
url='http://127.0.0.1:8765'
def read(path='/api/state'):
 with urllib.request.urlopen(url+path,timeout=10) as r:return json.load(r)
def send(data,path='/api/command'):
 req=urllib.request.Request(url+path,data=json.dumps(data).encode(),headers={'Content-Type':'application/json'})
 with urllib.request.urlopen(req,timeout=120) as r:ack=json.load(r)
 for _ in range(40):
  s=read()
  if s['experiment_id']==ack['experiment_id'] and s['revision']>=ack['revision']:return s
  time.sleep(.3)
 raise AssertionError('Command not observed in Ditto')
checks=[]
try:
 for scenario in ('fan','resistance','closure','gas','loss','blind_all','delay','freeze','bias','noise','outside','cancel'):
  send({'action':'reset'});send({'action':'pause'})
  s=send({'action':'scenario','name':scenario})
  assert s['connection']['source']=='Ditto'
  if scenario=='fan':assert s['params']['fan_a']==.8
  elif scenario=='resistance':assert s['params']['resistance_e6']==2 and s['flow_changes']['e6']<0
  elif scenario=='closure':assert s['air']['q']['e5']==0
  elif scenario=='gas':assert s['params']['gas']==2
  elif scenario=='loss':assert len(s['quality']['used_channels'])==5
  elif scenario=='blind_all':assert not s['quality']['used_channels']
  elif scenario=='delay':assert s['sensors']['c_V7']['delay_s']==15
  elif scenario=='freeze':assert s['sensors']['c_V7']['frozen']
  elif scenario=='bias':assert s['conflict']
  elif scenario=='noise':assert s['sensors']['c_V7']['noise']>0
  elif scenario=='outside':assert s['params']['gas']==3
  elif scenario=='cancel':assert len(s['quality']['used_channels'])==8
  checks.append('Scenario '+scenario+': command receipt and Ditto state verified')
 # A nontrivial paused experiment survives replay through the platform.
 send({'action':'scenario','name':'closure'});send({'action':'scenario','name':'gas'})
 saved=read('/api/export.json');truth=saved['state']['truth'];params=saved['state']['params']
 send({'action':'reset'})
 s=send(saved,'/api/replay')
 assert s['truth']==truth and s['params']==params and s['paused']
 assert s['connection']['source']=='Ditto'
 checks.append('JSON replay in platform mode: truth, parameters, pause and receipt verified through Ditto')
finally:send({'action':'reset'})
(root/'docs/ui-platform-check.json').write_text(json.dumps({'passed':True,'checked_at_unix':time.time(),'checks':checks},ensure_ascii=False,indent=2),encoding='utf8')
print('PASS',len(checks),'live UI/API checks')
