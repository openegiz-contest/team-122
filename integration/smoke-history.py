import json,base64,urllib.request,csv,io,time
from datetime import datetime,timezone
from pathlib import Path
root=Path(__file__).resolve().parent.parent
config=dict(line.split('=',1) for line in (root/'openegiz/deploy/compose/.env').read_text().splitlines() if line and not line.startswith('#') and '=' in line)
auth=base64.b64encode(('admin:'+config['GRAFANA_ADMIN_PASSWORD']).encode()).decode()
def get(path):
 req=urllib.request.Request('http://127.0.0.1:3000'+path,headers={'Authorization':'Basic '+auth})
 with urllib.request.urlopen(req,timeout=20) as r:return json.load(r)
dashboard=get('/api/dashboards/uid/ventobserve')['dashboard']
results=[]
for panel in dashboard['panels']:
 query=panel['targets'][0]['query'].replace('v.timeRangeStart','-5m').replace('v.timeRangeStop','now()').replace('v.windowPeriod','10s')
 req=urllib.request.Request('http://127.0.0.1:8086/api/v2/query?org=opentwins',data=json.dumps({'query':query,'type':'flux'}).encode(),headers={'Authorization':'Token '+config['INFLUXDB_TOKEN'],'Content-Type':'application/json','Accept':'application/csv'})
 with urllib.request.urlopen(req,timeout=30) as r:raw=r.read().decode()
 rows=list(csv.DictReader(io.StringIO(raw)))
 values=[r.get('_value') for r in rows if r.get('_value') and r['_value']!='_value']
 timestamps=[r.get('_time') for r in rows if r.get('_time') and r['_time']!='_time']
 age=(datetime.now(timezone.utc)-datetime.fromisoformat(timestamps[-1].replace('Z','+00:00'))).total_seconds() if timestamps else None
 results.append({'panel':panel['title'],'points':len(values),'latest':values[-1] if values else None,'latest_age_s':age})
print(json.dumps(results,ensure_ascii=False,indent=2))
(root/'docs/dashboard-check.json').write_text(json.dumps({'checked_at_unix':time.time(),'panels':results,'passed':all(r['points'] and r['latest_age_s']<30 for r in results)},ensure_ascii=False,indent=2),encoding='utf8')

assert all(r['points'] and r['latest_age_s']<30 for r in results), 'Missing or stale history'
