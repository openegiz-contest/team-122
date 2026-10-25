"""Prospective, fully enumerated synthetic policy audit. Never field evidence."""
import hashlib,itertools,json,math,random,time
from pathlib import Path
from .network import DEFAULT,SENSORS,solve,steady,advance,values
from .network_observer import Observer,GRID,TARGETS,bounds,width
from .network_twin import NetworkTwin

POLICIES=('proposed','simple','methane_priority','fastest','random_exact','no_repair','oracle')

def outcome(pool,future,truth_at_target,measurement,key,base):
    sensor=SENSORS[key]
    keep=[f for h,f in zip(pool,future) if abs(values(advance(h['c'],h['air'],h['p']['gas'],sensor['repair_s'])[0],h['air'])[key]-measurement)<=sensor['tolerance']+1e-9]
    conflict=not keep
    b=bounds(keep) if keep else None
    remaining=width(keep) if keep else base  # conflict earns no information credit
    contained=bool(b) and all(b[n]['low']-1e-8<=truth_at_target[n]*100<=b[n]['high']+1e-8 for n in TARGETS)
    threshold=1.0
    classification=None if b is None or b['V7']['low']<threshold<=b['V7']['high'] else b['V7']['low']>=threshold
    return {'remaining_width':remaining,'gain_per_cost':(base-remaining)/sensor['cost'],
            'cost':sensor['cost'],'repair_s':sensor['repair_s'],'contains_truth':int(contained),'conflict':int(conflict),
            'threshold_resolved':int(classification is not None),
            'threshold_wrong':int(classification is not None and classification!=(truth_at_target['V7']*100>=threshold))}

def summarize(records):
    valid=[r for r in records if not r['prior_conflict']]
    result={'cases':len(records),'prior_conflicts':len(records)-len(valid),'evaluated':len(valid),'strategies':{},'comparisons':{}}
    for policy in POLICIES:
        rows=[r['results'][policy] for r in valid]
        result['strategies'][policy]={key:sum(v[key] for v in rows)/len(rows) if rows else None for key in ('remaining_width','gain_per_cost','cost','repair_s','contains_truth','conflict','threshold_resolved','threshold_wrong')}
    for policy in POLICIES[1:]:
        d=[r['results']['proposed']['gain_per_cost']-r['results'][policy]['gain_per_cost'] for r in valid]
        w=[r['results'][policy]['remaining_width']-r['results']['proposed']['remaining_width'] for r in valid]
        result['comparisons'][policy]={'gain_per_cost':{'wins':sum(x>1e-9 for x in d),'ties':sum(abs(x)<=1e-9 for x in d),'losses':sum(x< -1e-9 for x in d),'worst_advantage':min(d,default=0)},
                                      'remaining_width':{'wins':sum(x>1e-9 for x in w),'ties':sum(abs(x)<=1e-9 for x in w),'losses':sum(x< -1e-9 for x in w)}}
    return result

def run():
    root=Path(__file__).resolve().parent.parent;plan=(root/'docs/SENSOR_UTILITY_PLAN.json').read_bytes()
    rng=random.Random(20261026)
    pairs=[('on_grid',r,g) for r,g in itertools.product(GRID,GRID)]+[('off_grid',math.exp(rng.uniform(math.log(.5),math.log(4))),math.exp(rng.uniform(math.log(.5),math.log(4)))) for _ in range(12)]
    masks={'all':list(SENSORS),'gas_only':[k for k in SENSORS if k.startswith('c')],
           'flow_only':[k for k in SENSORS if k.startswith('q')],'mixed':['q_e6','c_V7','c_V9']}
    records=[];started=time.monotonic()
    for group,resistance,gas in pairs:
      for fans,horizon,initial,(mask_name,missing),noise in itertools.product(((.8,1.),(1.,1.),(1.15,.8)),(60,180,600),('transient','equilibrium'),masks.items(),(-1,0,1)):
        p={**DEFAULT,'resistance_e6':resistance,'gas':gas,'fan_a':fans[0],'fan_b':fans[1]};air=solve(p)
        c=steady(solve()) if initial=='transient' else steady(air,gas)
        truth_target=advance(c,air,gas,horizon)[0];now=values(c,air)
        o=Observer()
        for h in o.hypotheses:
            h['p'].update(fan_a=fans[0],fan_b=fans[1]);h['air']=solve(h['p'])
            h['c']=dict(c) if initial=='transient' else steady(h['air'],h['p']['gas'])
        readings={k:None if k in missing else now[k]+noise*SENSORS[k]['tolerance'] for k in SENSORS}
        o.observe(readings,{k:{'usable':k not in missing} for k in SENSORS})
        record={'id':len(records),'group':group,'resistance_e6':resistance,'gas':gas,'fans':fans,'horizon_s':horizon,'initial':initial,'mask':mask_name,'noise_fraction':noise,'prior_conflict':o.conflict}
        if o.conflict:records.append(record);continue
        rank,_=o.rank(missing,horizon);future=o.forecast(horizon);base=width(future)
        spread={k:(max(values(h['c'],h['air'])[k] for h in o.pool)-min(values(h['c'],h['air'])[k] for h in o.pool))/SENSORS[k]['tolerance']/SENSORS[k]['cost'] for k in missing}
        choices={'proposed':rank[0]['sensor'],'simple':max(missing,key=lambda k:(spread[k],k)),
                 'methane_priority':max(missing,key=lambda k:(k.startswith('c'),spread[k],k)),
                 'fastest':min(missing,key=lambda k:(SENSORS[k]['repair_s'],SENSORS[k]['cost'],k))}
        outcomes={}
        for k in missing:
            measurement=values(advance(c,air,gas,SENSORS[k]['repair_s'])[0],air)[k]+noise*SENSORS[k]['tolerance']
            outcomes[k]=outcome(o.pool,future,truth_target,measurement,k,base)
        choices['oracle']=max(missing,key=lambda k:(outcomes[k]['gain_per_cost'],-outcomes[k]['remaining_width'],k))
        results={policy:{'sensor':key,**outcomes[key]} for policy,key in choices.items()}
        results['random_exact']={k:sum(v[k] for v in outcomes.values())/len(outcomes) for k in next(iter(outcomes.values()))}
        b=bounds(future);contained=all(b[n]['low']-1e-8<=truth_target[n]*100<=b[n]['high']+1e-8 for n in TARGETS)
        resolved=b['V7']['high']<1 or b['V7']['low']>=1
        results['no_repair']={'remaining_width':base,'gain_per_cost':0.,'cost':0.,'repair_s':0.,'contains_truth':int(contained),'conflict':0,'threshold_resolved':int(resolved),'threshold_wrong':int(resolved and (b['V7']['low']>=1)!=(truth_target['V7']*100>=1))}
        record.update(prior_width=base,results=results,all_outcomes=outcomes,predicted_gain=rank[0]['gain'])
        records.append(record)
      print(f'Completed parameter pair {len(records)}/6048',flush=True)
    groups={g:summarize([r for r in records if r['group']==g]) for g in ('on_grid','off_grid')}
    modes={mode:summarize([r for r in records if r['group']=='on_grid' and r['initial']==mode]) for mode in ('transient','equilibrium')}
    valid=[r for r in records if not r['prior_conflict'] and r['group']=='on_grid']
    ordered=sorted(valid,key=lambda r:r['results']['simple']['remaining_width']-r['results']['proposed']['remaining_width'])
    return {'model_signature':NetworkTwin.model_signature(),'study_signature':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'plan_sha256':hashlib.sha256(plan).hexdigest(),'cases':len(records),'elapsed_s':time.monotonic()-started,'groups':groups,'initial_modes':modes,
            'examples':{'least_advantage_vs_simple':ordered[0],'most_advantage_vs_simple':ordered[-1]},
            'limits':['synthetic deterministic factorial design, no independent field samples','noise fractions apply equally to available and repaired readings; no random noise probability claim',
                      'off-grid results include prior conflicts; conditional policy means exclude those and report their count',
                      'conflicting repair earns zero gain credit, and is not a zero-width estimate','1 percent is an illustrative research threshold, not a safety rule',
                      'one repair per strategy; costs differ, both raw width and cost-normalized gain reported','observer and ranking were not tuned on these outcomes'],
            'records':records}

if __name__=='__main__':
    result=run();path=Path(__file__).resolve().parent.parent/'docs/sensor-utility.json'
    path.write_text(json.dumps(result,ensure_ascii=False,separators=(',',':')),encoding='utf8')
    print(json.dumps({'cases':result['cases'],'groups':result['groups'],'elapsed_s':result['elapsed_s']},ensure_ascii=False,indent=2))
