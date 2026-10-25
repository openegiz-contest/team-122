"""Predeclared reproducible v3 study; see docs/NETWORK_EVALUATION_PLAN.md."""
import copy
import itertools
import json
import random
from pathlib import Path
from .network import DEFAULT, SENSORS, solve, steady, advance, values
from .network_observer import Observer, GRID, TARGETS, bounds, width
from .network_twin import NetworkTwin
from .reference import run as reference

def run():
    rng=random.Random(20261025);records=[]
    masks=[list(SENSORS),[k for k in SENSORS if k!='c_V7'],[k for k in SENSORS if k!='q_e6']]
    for initial_mode,resistance,gas,fan,horizon,mask in itertools.product(('steady','transient'),GRID,GRID,(.8,1.),(60,120,300),masks):
        p={**DEFAULT,'resistance_e6':resistance,'gas':gas,'fan_a':fan};a=solve(p);c=steady(a,gas);truth=values(c,a)
        if initial_mode=='transient':c=steady(solve());truth=values(c,a)
        target_truth=advance(c,a,gas,horizon)[0]
        o=Observer()
        # Equilibrium initial-condition matrix, declared in the plan.
        for h in o.hypotheses:
            h['p']['fan_a']=fan;h['air']=solve(h['p']);h['c']=steady(h['air'],h['p']['gas'])
            if initial_mode=='transient':h['c']=dict(c)
        readings={k:None if k in mask else truth[k] for k in SENSORS};metadata={k:{'usable':k not in mask} for k in SENSORS}
        o.observe(readings,metadata)
        if o.conflict:raise AssertionError('Inside-grid truth excluded')
        rankings,_=o.rank(mask,horizon);future=o.forecast(horizon);base=width(future)
        actual={};included={}
        for key in mask:
            delay=SENSORS[key]['repair_s'];measurement=values(advance(c,a,gas,delay)[0],a)[key]
            matching=[f for h,f in zip(o.pool,future) if abs(values(advance(h['c'],h['air'],h['p']['gas'],delay)[0],h['air'])[key]-measurement)<=SENSORS[key]['tolerance']+1e-9]
            actual[key]=width(matching);b=bounds(matching)
            included[key]=all(b[n]['low']-1e-8<=100*target_truth[n]<=b[n]['high']+1e-8 for n in TARGETS)
        simple=max(mask,key=lambda k:(max(values(h['c'],h['air'])[k] for h in o.pool)-min(values(h['c'],h['air'])[k] for h in o.pool))/SENSORS[k]['tolerance']/SENSORS[k]['cost'])
        chosen={'proposed':rankings[0]['sensor'],'simple':simple,'fixed':mask[0],'random':rng.choice(mask),'oracle':min(mask,key=lambda k:(actual[k],SENSORS[k]['cost'],k))}
        results={strategy:{'sensor':key,'remaining_width':actual[key],'gain':base-actual[key],
                 'repair_s':SENSORS[key]['repair_s'],'cost':SENSORS[key]['cost'],
                 'regret':actual[key]-min(actual.values()),'contains_truth':included[key]} for strategy,key in chosen.items()}
        records.append({'initial_mode':initial_mode,'resistance_e6':resistance,'gas':gas,'fan_a':fan,'horizon_s':horizon,'missing':mask,'prior_width':base,'results':results,'all_outcomes':actual})
    summary={}
    for strategy in ('proposed','simple','fixed','random','oracle'):
        rows=[r['results'][strategy] for r in records]
        summary[strategy]={'mean_remaining_width':sum(r['remaining_width'] for r in rows)/len(rows),
                           'mean_regret':sum(r['regret'] for r in rows)/len(rows),'containment_failures':sum(not r['contains_truth'] for r in rows),
                           'flowmeter_choices':sum(r['sensor'].startswith('q') for r in rows)}
    comparisons={}
    for strategy in ('simple','fixed','random','oracle'):
        deltas=[r['results']['proposed']['remaining_width']-r['results'][strategy]['remaining_width'] for r in records]
        comparisons[strategy]={'proposed_better':sum(d< -1e-9 for d in deltas),'equal':sum(abs(d)<=1e-9 for d in deltas),'proposed_worse':sum(d>1e-9 for d in deltas)}
    stress=[]
    for scenario in ('noise','delay','freeze','bias','outside','blind_all'):
        t=NetworkTwin();t.command({'action':'scenario','name':scenario})
        for _ in range(20):t.tick(30)
        s=t.snapshot
        stress.append({'scenario':scenario,'conflict':s['conflict'],'used':s['quality']['used_channels'],
                       'truth_outside_displayed_envelope':[n for n in TARGETS if not s['estimate'][n]['low']-1e-9<=s['truth']['gas_pct'][n]<=s['estimate'][n]['high']+1e-9]})
    a=solve();c=steady(a);five,l=advance(c,a,2,600);one,_=advance(c,a,2,600,max_step=1);half,_=advance(c,a,2,600,max_step=.5)
    t=NetworkTwin();t.command({'action':'scenario','name':'blind_all'});t.params['gas']=3.;t.tick(600)
    stress.append({'scenario':'unannounced_source_change_while_blind','conflict':t.snapshot['conflict'],
                   'truth_outside_displayed_envelope':[n for n in TARGETS if not t.snapshot['estimate'][n]['low']<=t.gas[n]*100<=t.snapshot['estimate'][n]['high']]})
    groups={}
    for mode in ('steady','transient'):
        rows=[r for r in records if r['initial_mode']==mode];groups[mode]={}
        for strategy in summary:
            groups[mode][strategy]={'mean_remaining_width':sum(r['results'][strategy]['remaining_width'] for r in rows)/len(rows),
                                  'flowmeter_choices':sum(r['results'][strategy]['sensor'].startswith('q') for r in rows)}
    return {'model_signature':NetworkTwin.model_signature(),'model':'gucheng-network-v3','plan':'docs/NETWORK_EVALUATION_PLAN.md','cases':len(records),
            'summary':summary,'groups':groups,'comparisons':comparisons,'stress':stress,'reference':reference(),
            'numerics':{'mass_residual_m3':l['mass_residual_m3'],'dt5_vs_half_max_pp':max(abs(five[n]-half[n])*100 for n in c),'dt1_vs_half_max_pp':max(abs(one[n]-half[n])*100 for n in c)},
            'limits':['finite parameter grid','288 steady + 288 supplemental transient initial-condition cases','uniform hypothetical outcomes are not probabilities','one fixed random choice per case','no industrial or field validation'],
            'records':records}

if __name__=='__main__':
    result=run();Path('docs/network-evaluation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('records','reference')},ensure_ascii=False,indent=2))
